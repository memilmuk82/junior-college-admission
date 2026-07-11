from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from sqlalchemy.orm import Session

from app.services.eligibility import (
    EligibilityStatus,
    EligibilityTrace,
    StudentFacts,
    evaluate_eligibility,
    validate_eligibility_rule_payload,
)
from app.services.published_rules import (
    PublishedRule,
    load_published_disqualification_rule,
    load_published_multiple_application_rule,
    require_published_rule_usable,
    to_eligibility_rule,
)

IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
REASON_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,119}$")
MAX_FORBIDDEN_COMBINATIONS = 500


class PolicySchemaError(ValueError):
    pass


class MultipleApplicationStatus(StrEnum):
    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class DisqualificationStatus(StrEnum):
    CLEAR = "CLEAR"
    DISQUALIFIED = "DISQUALIFIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class ApplicationChoice:
    track_id: str
    institution_id: str
    campus_id: str

    def __post_init__(self) -> None:
        for name in ("track_id", "institution_id", "campus_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or len(value) > 120:
                raise ValueError(f"{name}은 1~120자 식별자여야 합니다.")


@dataclass(frozen=True)
class ApplicationHistory:
    choices: tuple[ApplicationChoice, ...]
    is_complete: bool

    def __post_init__(self) -> None:
        if not isinstance(self.is_complete, bool):
            raise ValueError("is_complete는 bool이어야 합니다.")
        if len(self.choices) > 500:
            raise ValueError("지원 이력은 최대 500건까지 평가할 수 있습니다.")


@dataclass(frozen=True)
class MultipleApplicationTrace:
    rule_id: str
    rule_version: str
    evaluated_application_count: int
    matched_constraint: str | None


@dataclass(frozen=True)
class MultipleApplicationDecision:
    status: MultipleApplicationStatus
    reason_code: str
    trace: MultipleApplicationTrace


@dataclass(frozen=True)
class SensitiveDisqualificationFacts:
    values: Mapping[str, bool]

    def __post_init__(self) -> None:
        normalized: dict[str, bool] = {}
        for name, value in self.values.items():
            if not IDENTIFIER_PATTERN.fullmatch(name):
                raise ValueError(f"허용되지 않은 민감 사실 이름입니다: {name}")
            if not isinstance(value, bool):
                raise ValueError(f"민감 결격 사실은 bool만 허용합니다: {name}")
            normalized[name] = value
        object.__setattr__(self, "values", MappingProxyType(normalized))


@dataclass(frozen=True)
class DisqualificationDecision:
    status: DisqualificationStatus
    reason_code: str
    missing_facts: tuple[str, ...]
    trace: EligibilityTrace


@dataclass(frozen=True)
class _MultipleApplicationPolicy:
    total_limit: int | None
    campus_limit: int | None
    forbidden_combinations: tuple[frozenset[str], ...]
    reason_codes: Mapping[str, str]


def evaluate_multiple_application(
    *,
    candidate: ApplicationChoice,
    history: ApplicationHistory,
    rule: PublishedRule,
) -> MultipleApplicationDecision:
    require_published_rule_usable(rule)
    policy = _parse_multiple_application_policy(rule.payload)
    institution_choices = tuple(
        choice for choice in history.choices if choice.institution_id == candidate.institution_id
    )
    evaluated_count = len(institution_choices) + 1

    if not history.is_complete:
        return _multiple_decision(
            rule,
            policy,
            status=MultipleApplicationStatus.NEEDS_REVIEW,
            reason_key="history_incomplete",
            evaluated_count=evaluated_count,
            matched_constraint="history_incomplete",
        )

    candidate_pairs = (
        frozenset({choice.track_id, candidate.track_id}) for choice in institution_choices
    )
    if any(pair in policy.forbidden_combinations for pair in candidate_pairs):
        return _multiple_decision(
            rule,
            policy,
            status=MultipleApplicationStatus.BLOCKED,
            reason_key="forbidden_combination",
            evaluated_count=evaluated_count,
            matched_constraint="forbidden_combination",
        )
    if policy.total_limit is not None and evaluated_count > policy.total_limit:
        return _multiple_decision(
            rule,
            policy,
            status=MultipleApplicationStatus.BLOCKED,
            reason_key="max_applications",
            evaluated_count=evaluated_count,
            matched_constraint="max_applications",
        )
    campus_count = (
        sum(choice.campus_id == candidate.campus_id for choice in institution_choices) + 1
    )
    if policy.campus_limit is not None and campus_count > policy.campus_limit:
        return _multiple_decision(
            rule,
            policy,
            status=MultipleApplicationStatus.BLOCKED,
            reason_key="max_per_campus",
            evaluated_count=evaluated_count,
            matched_constraint="max_per_campus",
        )
    return _multiple_decision(
        rule,
        policy,
        status=MultipleApplicationStatus.ALLOWED,
        reason_key="allowed",
        evaluated_count=evaluated_count,
        matched_constraint=None,
    )


def evaluate_disqualification(
    *,
    facts: SensitiveDisqualificationFacts,
    rule: PublishedRule,
) -> DisqualificationDecision:
    require_published_rule_usable(rule)
    validate_disqualification_rule_payload(rule.payload)
    eligibility_decision = evaluate_eligibility(
        StudentFacts(additional=facts.values),
        to_eligibility_rule(rule),
    )
    status_map = {
        EligibilityStatus.ELIGIBLE: DisqualificationStatus.CLEAR,
        EligibilityStatus.INELIGIBLE: DisqualificationStatus.DISQUALIFIED,
        EligibilityStatus.NEEDS_REVIEW: DisqualificationStatus.NEEDS_REVIEW,
        EligibilityStatus.INSUFFICIENT_DATA: DisqualificationStatus.INSUFFICIENT_DATA,
    }
    try:
        status = status_map[eligibility_decision.status]
    except KeyError as error:
        raise PolicySchemaError(
            "결격 규칙은 CONDITIONALLY_ELIGIBLE 상태를 사용할 수 없습니다."
        ) from error
    return DisqualificationDecision(
        status=status,
        reason_code=eligibility_decision.reason_code,
        missing_facts=eligibility_decision.missing_facts,
        trace=eligibility_decision.trace,
    )


def evaluate_published_disqualification(
    session: Session,
    admission_track_id: str,
    facts: SensitiveDisqualificationFacts,
) -> DisqualificationDecision:
    rule = load_published_disqualification_rule(session, admission_track_id)
    return evaluate_disqualification(facts=facts, rule=rule)


def evaluate_published_multiple_application(
    session: Session,
    admission_track_id: str,
    *,
    candidate: ApplicationChoice,
    history: ApplicationHistory,
) -> MultipleApplicationDecision:
    rule = load_published_multiple_application_rule(session, admission_track_id)
    return evaluate_multiple_application(candidate=candidate, history=history, rule=rule)


def validate_multiple_application_rule_payload(payload: Mapping[str, object]) -> None:
    _parse_multiple_application_policy(payload)


def validate_disqualification_rule_payload(payload: Mapping[str, object]) -> None:
    validate_eligibility_rule_payload(payload)
    _validate_disqualification_payload(payload)


def _multiple_decision(
    rule: PublishedRule,
    policy: _MultipleApplicationPolicy,
    *,
    status: MultipleApplicationStatus,
    reason_key: str,
    evaluated_count: int,
    matched_constraint: str | None,
) -> MultipleApplicationDecision:
    return MultipleApplicationDecision(
        status=status,
        reason_code=policy.reason_codes[reason_key],
        trace=MultipleApplicationTrace(
            rule_id=rule.rule_id,
            rule_version=rule.version,
            evaluated_application_count=evaluated_count,
            matched_constraint=matched_constraint,
        ),
    )


def _parse_multiple_application_policy(
    payload: Mapping[str, object],
) -> _MultipleApplicationPolicy:
    _require_exact_keys(
        payload,
        {
            "schema_version",
            "limits",
            "forbidden_track_combinations",
            "reason_codes",
        },
        "payload",
    )
    if payload.get("schema_version") != 1:
        raise PolicySchemaError("복수지원 규칙 schema_version은 1이어야 합니다.")
    limits = payload.get("limits")
    if not isinstance(limits, dict):
        raise PolicySchemaError("limits는 JSON 객체여야 합니다.")
    _require_exact_keys(limits, {"total", "per_campus"}, "limits")
    total_limit = _optional_positive_int(limits.get("total"), "limits.total")
    campus_limit = _optional_positive_int(limits.get("per_campus"), "limits.per_campus")

    raw_combinations = payload.get("forbidden_track_combinations")
    if not isinstance(raw_combinations, list) or len(raw_combinations) > MAX_FORBIDDEN_COMBINATIONS:
        raise PolicySchemaError(
            f"forbidden_track_combinations는 최대 {MAX_FORBIDDEN_COMBINATIONS}개 배열이어야 합니다."
        )
    combinations: list[frozenset[str]] = []
    for index, raw_combination in enumerate(raw_combinations):
        if (
            not isinstance(raw_combination, list)
            or len(raw_combination) != 2
            or not all(
                isinstance(track_id, str) and 0 < len(track_id) <= 120
                for track_id in raw_combination
            )
            or raw_combination[0] == raw_combination[1]
        ):
            raise PolicySchemaError(
                f"forbidden_track_combinations[{index}]는 서로 다른 전형 ID 2개여야 합니다."
            )
        combination = frozenset(raw_combination)
        if combination in combinations:
            raise PolicySchemaError("금지 전형 조합이 중복되었습니다.")
        combinations.append(combination)

    reason_codes = payload.get("reason_codes")
    if not isinstance(reason_codes, dict):
        raise PolicySchemaError("reason_codes는 JSON 객체여야 합니다.")
    expected_reason_keys = {
        "allowed",
        "history_incomplete",
        "max_applications",
        "max_per_campus",
        "forbidden_combination",
    }
    _require_exact_keys(reason_codes, expected_reason_keys, "reason_codes")
    normalized_reason_codes: dict[str, str] = {}
    for key in sorted(expected_reason_keys):
        value = reason_codes.get(key)
        if not isinstance(value, str) or not REASON_CODE_PATTERN.fullmatch(value):
            raise PolicySchemaError(f"reason_codes.{key}는 대문자 reason code여야 합니다.")
        normalized_reason_codes[key] = value
    return _MultipleApplicationPolicy(
        total_limit=total_limit,
        campus_limit=campus_limit,
        forbidden_combinations=tuple(combinations),
        reason_codes=MappingProxyType(normalized_reason_codes),
    )


def _validate_disqualification_payload(payload: Mapping[str, object]) -> None:
    cases = payload.get("cases")
    default = payload.get("default")
    if not isinstance(cases, list) or not isinstance(default, dict):
        raise PolicySchemaError("결격 규칙은 지원자격 DSL v1 구조여야 합니다.")
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise PolicySchemaError(f"cases[{index}]는 JSON 객체여야 합니다.")
        status = case.get("status")
        if status not in {"INELIGIBLE", "NEEDS_REVIEW"}:
            raise PolicySchemaError("결격 case 상태는 INELIGIBLE 또는 NEEDS_REVIEW만 허용합니다.")
        _validate_sensitive_condition(case.get("when"), f"cases[{index}].when")
    if default.get("status") not in {"ELIGIBLE", "NEEDS_REVIEW"}:
        raise PolicySchemaError("결격 default 상태는 ELIGIBLE 또는 NEEDS_REVIEW만 허용합니다.")


def _validate_sensitive_condition(raw: object, path: str) -> None:
    if not isinstance(raw, dict):
        raise PolicySchemaError(f"{path}는 JSON 객체여야 합니다.")
    group_keys = set(raw) & {"all", "any", "not"}
    if group_keys:
        if len(group_keys) != 1:
            raise PolicySchemaError(f"{path}의 조건 조합이 잘못되었습니다.")
        operator = next(iter(group_keys))
        children = [raw[operator]] if operator == "not" else raw[operator]
        if not isinstance(children, list) or not children:
            raise PolicySchemaError(f"{path}.{operator} 조건이 비어 있습니다.")
        for index, child in enumerate(children):
            _validate_sensitive_condition(child, f"{path}.{operator}[{index}]")
        return
    fact_name = raw.get("fact")
    if (
        not isinstance(fact_name, str)
        or not fact_name.startswith("additional.")
        or not IDENTIFIER_PATTERN.fullmatch(fact_name.removeprefix("additional."))
    ):
        raise PolicySchemaError("결격 규칙은 세션 전용 additional 사실만 사용할 수 있습니다.")
    if raw.get("op") not in {"is_true", "is_false"}:
        raise PolicySchemaError("결격 사실에는 is_true 또는 is_false만 허용합니다.")


def _optional_positive_int(value: object, path: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PolicySchemaError(f"{path}는 양의 정수 또는 null이어야 합니다.")
    return value


def _require_exact_keys(value: Mapping[str, object], expected: set[str], path: str) -> None:
    actual = set(value)
    if actual != expected:
        raise PolicySchemaError(
            f"{path} 필드가 계약과 다릅니다. expected={sorted(expected)}, actual={sorted(actual)}"
        )


__all__ = [
    "ApplicationChoice",
    "ApplicationHistory",
    "DisqualificationDecision",
    "DisqualificationStatus",
    "MultipleApplicationDecision",
    "MultipleApplicationStatus",
    "PolicySchemaError",
    "SensitiveDisqualificationFacts",
    "evaluate_disqualification",
    "evaluate_multiple_application",
    "evaluate_published_disqualification",
    "evaluate_published_multiple_application",
    "validate_disqualification_rule_payload",
    "validate_multiple_application_rule_payload",
]
