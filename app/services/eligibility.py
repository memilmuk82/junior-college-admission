from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import TypeGuard

type Scalar = str | int | float | bool

MAX_CASES = 100
MAX_CONDITION_DEPTH = 20
MAX_CONDITION_NODES = 500
MAX_LIST_VALUES = 100

IDENTIFIER_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
REASON_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{0,119}$")

SCHOOL_TYPES = {
    "GENERAL",
    "VOCATIONAL",
    "MEISTER",
    "COMPREHENSIVE_VOCATIONAL",
    "LIFELONG_EDUCATION",
    "FOREIGN",
}
GRADUATION_STATUSES = {"EXPECTED", "GRADUATED", "NOT_GRADUATED"}
VOCATIONAL_TRAINING_STATUSES = {
    "NONE",
    "PARTICIPATING",
    "EXPECTED_COMPLETION",
    "COMPLETED",
}

BASE_FACT_NAMES = {
    "home_school_type",
    "final_school_type",
    "graduation_status",
    "vocational_training_status",
    "vocational_training_semesters",
    "vocational_training_hours",
    "vocational_training_months",
    "transferred",
    "ged",
}
BOOLEAN_FACT_NAMES = {"transferred", "ged"}
NUMERIC_FACT_NAMES = {
    "vocational_training_semesters",
    "vocational_training_hours",
    "vocational_training_months",
}
STRING_FACT_NAMES = BASE_FACT_NAMES - BOOLEAN_FACT_NAMES - NUMERIC_FACT_NAMES
LEAF_OPERATORS = {"eq", "ne", "in", "not_in", "gte", "lte", "is_true", "is_false"}


class EligibilityError(ValueError):
    pass


class RuleSchemaError(EligibilityError):
    pass


class UnusableEligibilityRule(EligibilityError):
    pass


class ScoreCalculationBlocked(EligibilityError):
    pass


class EligibilityStatus(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    CONDITIONALLY_ELIGIBLE = "CONDITIONALLY_ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ConditionOutcome(StrEnum):
    MATCH = "MATCH"
    NO_MATCH = "NO_MATCH"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class StudentFacts:
    home_school_type: str | None = None
    final_school_type: str | None = None
    graduation_status: str | None = None
    vocational_training_status: str | None = None
    vocational_training_semesters: int | None = None
    vocational_training_hours: int | None = None
    vocational_training_months: int | None = None
    transferred: bool | None = None
    ged: bool | None = None
    additional: Mapping[str, Scalar] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_enum_fact("home_school_type", self.home_school_type, SCHOOL_TYPES)
        _validate_enum_fact("final_school_type", self.final_school_type, SCHOOL_TYPES)
        _validate_enum_fact("graduation_status", self.graduation_status, GRADUATION_STATUSES)
        _validate_enum_fact(
            "vocational_training_status",
            self.vocational_training_status,
            VOCATIONAL_TRAINING_STATUSES,
        )
        for name in (
            "vocational_training_semesters",
            "vocational_training_hours",
            "vocational_training_months",
        ):
            value = getattr(self, name)
            if value is not None and (
                not isinstance(value, int) or isinstance(value, bool) or value < 0
            ):
                raise ValueError(f"{name}은 0 이상의 정수여야 합니다.")
        for name in ("transferred", "ged"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{name}은 bool 또는 None이어야 합니다.")
        normalized_additional: dict[str, Scalar] = {}
        for name, value in self.additional.items():
            if not IDENTIFIER_PATTERN.fullmatch(name):
                raise ValueError(f"허용되지 않은 추가 사실 이름입니다: {name}")
            if not _is_scalar(value):
                raise ValueError(f"추가 사실은 문자열·숫자·bool만 허용합니다: {name}")
            normalized_additional[name] = value
        object.__setattr__(self, "additional", MappingProxyType(normalized_additional))


@dataclass(frozen=True)
class EligibilityRule:
    rule_id: str
    version: str
    lifecycle_status: str
    payload: Mapping[str, object]
    source_citation_id: str | None
    independent_verified: bool
    golden_test_ref: str | None
    human_approved_at: datetime | None


@dataclass(frozen=True)
class ConditionTrace:
    case_id: str
    path: str
    fact: str
    operator: str
    outcome: ConditionOutcome


@dataclass(frozen=True)
class EligibilityTrace:
    rule_id: str
    rule_version: str
    conditions: tuple[ConditionTrace, ...]


@dataclass(frozen=True)
class EligibilityDecision:
    status: EligibilityStatus
    reason_code: str
    matched_case_id: str | None
    missing_facts: tuple[str, ...]
    trace: EligibilityTrace

    @property
    def is_confirmed(self) -> bool:
        return self.status not in {
            EligibilityStatus.NEEDS_REVIEW,
            EligibilityStatus.INSUFFICIENT_DATA,
        }

    @property
    def allows_score_calculation(self) -> bool:
        return self.status in {
            EligibilityStatus.ELIGIBLE,
            EligibilityStatus.CONDITIONALLY_ELIGIBLE,
        }


@dataclass(frozen=True)
class _LeafCondition:
    fact: str
    operator: str
    expected: Scalar | tuple[Scalar, ...] | None


@dataclass(frozen=True)
class _GroupCondition:
    operator: str
    children: tuple[_Condition, ...]


type _Condition = _LeafCondition | _GroupCondition


@dataclass(frozen=True)
class _RuleCase:
    case_id: str
    condition: _Condition
    status: EligibilityStatus
    reason_code: str


@dataclass(frozen=True)
class _ParsedRule:
    cases: tuple[_RuleCase, ...]
    default_status: EligibilityStatus
    default_reason_code: str


@dataclass
class _ParseBudget:
    nodes: int = 0


@dataclass(frozen=True)
class _ConditionEvaluation:
    outcome: ConditionOutcome
    missing_facts: frozenset[str]


def evaluate_eligibility(facts: StudentFacts, rule: EligibilityRule) -> EligibilityDecision:
    _require_runnable_rule(rule)
    parsed = _parse_rule_payload(rule.payload)
    traces: list[ConditionTrace] = []
    unresolved_facts: set[str] = set()

    for case in parsed.cases:
        evaluation = _evaluate_condition(
            case.condition,
            facts,
            case_id=case.case_id,
            path="when",
            traces=traces,
        )
        if evaluation.outcome is ConditionOutcome.MATCH:
            return _decision(
                rule,
                status=case.status,
                reason_code=case.reason_code,
                matched_case_id=case.case_id,
                missing_facts=(),
                traces=traces,
            )
        if evaluation.outcome is ConditionOutcome.UNKNOWN:
            unresolved_facts.update(evaluation.missing_facts)

    if unresolved_facts:
        return _decision(
            rule,
            status=EligibilityStatus.INSUFFICIENT_DATA,
            reason_code="INSUFFICIENT_DATA",
            matched_case_id=None,
            missing_facts=tuple(sorted(unresolved_facts)),
            traces=traces,
        )
    return _decision(
        rule,
        status=parsed.default_status,
        reason_code=parsed.default_reason_code,
        matched_case_id=None,
        missing_facts=(),
        traces=traces,
    )


def validate_eligibility_rule_payload(payload: Mapping[str, object]) -> None:
    _parse_rule_payload(payload)


def require_score_calculation_allowed(decision: EligibilityDecision) -> None:
    if not decision.allows_score_calculation:
        raise ScoreCalculationBlocked(
            f"지원자격 상태 {decision.status.value}에서는 성적 계산을 시작할 수 없습니다."
        )


def _decision(
    rule: EligibilityRule,
    *,
    status: EligibilityStatus,
    reason_code: str,
    matched_case_id: str | None,
    missing_facts: tuple[str, ...],
    traces: list[ConditionTrace],
) -> EligibilityDecision:
    return EligibilityDecision(
        status=status,
        reason_code=reason_code,
        matched_case_id=matched_case_id,
        missing_facts=missing_facts,
        trace=EligibilityTrace(
            rule_id=rule.rule_id,
            rule_version=rule.version,
            conditions=tuple(traces),
        ),
    )


def _require_runnable_rule(rule: EligibilityRule) -> None:
    if rule.lifecycle_status != "PUBLISHED":
        raise UnusableEligibilityRule("PUBLISHED 상태의 지원자격 규칙만 실행할 수 있습니다.")
    if (
        not rule.source_citation_id
        or not rule.independent_verified
        or not rule.golden_test_ref
        or rule.human_approved_at is None
    ):
        raise UnusableEligibilityRule(
            "근거·독립 검증·골든 테스트·사람 승인이 모두 있는 규칙만 실행할 수 있습니다."
        )


def _parse_rule_payload(payload: Mapping[str, object]) -> _ParsedRule:
    _require_exact_keys(payload, {"schema_version", "cases", "default"}, "payload")
    if payload.get("schema_version") != 1:
        raise RuleSchemaError("지원자격 규칙 schema_version은 1이어야 합니다.")
    cases_payload = payload.get("cases")
    if not isinstance(cases_payload, list):
        raise RuleSchemaError("cases는 JSON 배열이어야 합니다.")
    if len(cases_payload) > MAX_CASES:
        raise RuleSchemaError(f"cases는 최대 {MAX_CASES}개까지 허용합니다.")

    budget = _ParseBudget()
    cases: list[_RuleCase] = []
    seen_case_ids: set[str] = set()
    for index, raw_case in enumerate(cases_payload):
        if not isinstance(raw_case, dict):
            raise RuleSchemaError(f"cases[{index}]는 JSON 객체여야 합니다.")
        _require_exact_keys(
            raw_case, {"case_id", "when", "status", "reason_code"}, f"cases[{index}]"
        )
        case_id = _bounded_identifier(raw_case.get("case_id"), f"cases[{index}].case_id")
        if case_id in seen_case_ids:
            raise RuleSchemaError(f"case_id가 중복되었습니다: {case_id}")
        seen_case_ids.add(case_id)
        cases.append(
            _RuleCase(
                case_id=case_id,
                condition=_parse_condition(
                    raw_case.get("when"), depth=1, budget=budget, path=f"cases[{index}].when"
                ),
                status=_parse_status(raw_case.get("status"), f"cases[{index}].status"),
                reason_code=_reason_code(
                    raw_case.get("reason_code"), f"cases[{index}].reason_code"
                ),
            )
        )

    default = payload.get("default")
    if not isinstance(default, dict):
        raise RuleSchemaError("default는 JSON 객체여야 합니다.")
    _require_exact_keys(default, {"status", "reason_code"}, "default")
    return _ParsedRule(
        cases=tuple(cases),
        default_status=_parse_status(default.get("status"), "default.status"),
        default_reason_code=_reason_code(default.get("reason_code"), "default.reason_code"),
    )


def _parse_condition(raw: object, *, depth: int, budget: _ParseBudget, path: str) -> _Condition:
    budget.nodes += 1
    if budget.nodes > MAX_CONDITION_NODES:
        raise RuleSchemaError(f"조건 노드는 최대 {MAX_CONDITION_NODES}개까지 허용합니다.")
    if depth > MAX_CONDITION_DEPTH:
        raise RuleSchemaError(f"조건 깊이는 최대 {MAX_CONDITION_DEPTH}까지 허용합니다.")
    if not isinstance(raw, dict):
        raise RuleSchemaError(f"{path}는 JSON 객체여야 합니다.")

    group_keys = set(raw) & {"all", "any", "not"}
    if group_keys:
        if len(group_keys) != 1 or len(raw) != 1:
            raise RuleSchemaError(f"{path}는 all, any, not 중 하나만 가져야 합니다.")
        operator = next(iter(group_keys))
        value = raw[operator]
        if operator == "not":
            return _GroupCondition(
                operator="not",
                children=(
                    _parse_condition(value, depth=depth + 1, budget=budget, path=f"{path}.not"),
                ),
            )
        if not isinstance(value, list) or not value:
            raise RuleSchemaError(f"{path}.{operator}는 비어 있지 않은 배열이어야 합니다.")
        if len(value) > MAX_LIST_VALUES:
            raise RuleSchemaError(
                f"{path}.{operator}는 최대 {MAX_LIST_VALUES}개 조건까지 허용합니다."
            )
        return _GroupCondition(
            operator=operator,
            children=tuple(
                _parse_condition(
                    child,
                    depth=depth + 1,
                    budget=budget,
                    path=f"{path}.{operator}[{index}]",
                )
                for index, child in enumerate(value)
            ),
        )

    if "fact" not in raw or "op" not in raw:
        raise RuleSchemaError(f"{path}는 제한형 조건 형식이 아닙니다.")
    operator = raw.get("op")
    if not isinstance(operator, str) or operator not in LEAF_OPERATORS:
        raise RuleSchemaError(f"허용되지 않은 조건 연산자입니다: {operator}")
    required_keys = (
        {"fact", "op"}
        if operator in {"is_true", "is_false"}
        else {
            "fact",
            "op",
            "value",
        }
    )
    _require_exact_keys(raw, required_keys, path)
    fact_name = _fact_name(raw.get("fact"))
    _validate_operator_for_fact(fact_name, operator)
    expected = (
        None
        if operator in {"is_true", "is_false"}
        else _expected_value(raw.get("value"), operator, path)
    )
    _validate_expected_for_fact(fact_name, operator, expected)
    return _LeafCondition(fact=fact_name, operator=operator, expected=expected)


def _evaluate_condition(
    condition: _Condition,
    facts: StudentFacts,
    *,
    case_id: str,
    path: str,
    traces: list[ConditionTrace],
) -> _ConditionEvaluation:
    if isinstance(condition, _LeafCondition):
        actual = _fact_value(facts, condition.fact)
        if actual is None:
            outcome = ConditionOutcome.UNKNOWN
            missing = frozenset({condition.fact})
        else:
            outcome = (
                ConditionOutcome.MATCH
                if _compare(actual, condition.operator, condition.expected)
                else ConditionOutcome.NO_MATCH
            )
            missing = frozenset()
        traces.append(
            ConditionTrace(
                case_id=case_id,
                path=path,
                fact=condition.fact,
                operator=condition.operator,
                outcome=outcome,
            )
        )
        return _ConditionEvaluation(outcome, missing)

    children = [
        _evaluate_condition(
            child,
            facts,
            case_id=case_id,
            path=f"{path}.{condition.operator}[{index}]",
            traces=traces,
        )
        for index, child in enumerate(condition.children)
    ]
    if condition.operator == "not":
        child = children[0]
        if child.outcome is ConditionOutcome.UNKNOWN:
            return child
        return _ConditionEvaluation(
            ConditionOutcome.NO_MATCH
            if child.outcome is ConditionOutcome.MATCH
            else ConditionOutcome.MATCH,
            frozenset(),
        )
    if condition.operator == "all":
        if any(child.outcome is ConditionOutcome.NO_MATCH for child in children):
            return _ConditionEvaluation(ConditionOutcome.NO_MATCH, frozenset())
        if any(child.outcome is ConditionOutcome.UNKNOWN for child in children):
            return _ConditionEvaluation(
                ConditionOutcome.UNKNOWN,
                frozenset().union(*(child.missing_facts for child in children)),
            )
        return _ConditionEvaluation(ConditionOutcome.MATCH, frozenset())
    if any(child.outcome is ConditionOutcome.MATCH for child in children):
        return _ConditionEvaluation(ConditionOutcome.MATCH, frozenset())
    if any(child.outcome is ConditionOutcome.UNKNOWN for child in children):
        return _ConditionEvaluation(
            ConditionOutcome.UNKNOWN,
            frozenset().union(*(child.missing_facts for child in children)),
        )
    return _ConditionEvaluation(ConditionOutcome.NO_MATCH, frozenset())


def _fact_value(facts: StudentFacts, name: str) -> Scalar | None:
    if name.startswith("additional."):
        return facts.additional.get(name.removeprefix("additional."))
    value = getattr(facts, name)
    return value if isinstance(value, (str, int, float, bool)) else None


def _compare(actual: Scalar, operator: str, expected: Scalar | tuple[Scalar, ...] | None) -> bool:
    if operator == "is_true":
        return actual is True
    if operator == "is_false":
        return actual is False
    if operator == "eq":
        return actual == expected
    if operator == "ne":
        return actual != expected
    if operator == "in":
        return isinstance(expected, tuple) and actual in expected
    if operator == "not_in":
        return isinstance(expected, tuple) and actual not in expected
    if not _is_number(actual) or not _is_number(expected):
        return False
    return actual >= expected if operator == "gte" else actual <= expected


def _fact_name(raw: object) -> str:
    if not isinstance(raw, str):
        raise RuleSchemaError("fact는 문자열이어야 합니다.")
    if raw in BASE_FACT_NAMES:
        return raw
    if raw.startswith("additional."):
        additional_name = raw.removeprefix("additional.")
        if IDENTIFIER_PATTERN.fullmatch(additional_name):
            return raw
    raise RuleSchemaError(f"허용되지 않은 학생 사실 필드입니다: {raw}")


def _validate_operator_for_fact(fact_name: str, operator: str) -> None:
    if fact_name in BOOLEAN_FACT_NAMES and operator not in {
        "eq",
        "ne",
        "is_true",
        "is_false",
    }:
        raise RuleSchemaError(f"bool 사실에 허용되지 않은 연산자입니다: {operator}")
    if fact_name in NUMERIC_FACT_NAMES and operator in {"is_true", "is_false"}:
        raise RuleSchemaError(f"숫자 사실에 허용되지 않은 연산자입니다: {operator}")
    if fact_name in STRING_FACT_NAMES and operator in {"gte", "lte", "is_true", "is_false"}:
        raise RuleSchemaError(f"문자열 사실에 허용되지 않은 연산자입니다: {operator}")


def _validate_expected_for_fact(
    fact_name: str,
    operator: str,
    expected: Scalar | tuple[Scalar, ...] | None,
) -> None:
    if fact_name.startswith("additional.") or expected is None:
        return
    values = expected if isinstance(expected, tuple) else (expected,)
    if fact_name in BOOLEAN_FACT_NAMES and not all(isinstance(value, bool) for value in values):
        raise RuleSchemaError(f"{fact_name} 조건값은 bool이어야 합니다.")
    if fact_name in NUMERIC_FACT_NAMES and not all(_is_number(value) for value in values):
        raise RuleSchemaError(f"{fact_name} 조건값은 숫자여야 합니다.")
    allowed_values: set[str] | None = None
    if fact_name in {"home_school_type", "final_school_type"}:
        allowed_values = SCHOOL_TYPES
    elif fact_name == "graduation_status":
        allowed_values = GRADUATION_STATUSES
    elif fact_name == "vocational_training_status":
        allowed_values = VOCATIONAL_TRAINING_STATUSES
    if allowed_values is not None and not all(
        isinstance(value, str) and value in allowed_values for value in values
    ):
        raise RuleSchemaError(f"{fact_name}에 허용되지 않은 조건값이 있습니다.")


def _expected_value(raw: object, operator: str, path: str) -> Scalar | tuple[Scalar, ...]:
    if operator in {"in", "not_in"}:
        if not isinstance(raw, list) or not raw or len(raw) > MAX_LIST_VALUES:
            raise RuleSchemaError(f"{path}.value는 1~{MAX_LIST_VALUES}개의 값 배열이어야 합니다.")
        if not all(_is_scalar(value) for value in raw):
            raise RuleSchemaError(f"{path}.value에는 문자열·숫자·bool만 허용합니다.")
        return tuple(raw)
    if not _is_scalar(raw):
        raise RuleSchemaError(f"{path}.value는 문자열·숫자·bool이어야 합니다.")
    if operator in {"gte", "lte"} and not _is_number(raw):
        raise RuleSchemaError(f"{path}.value는 숫자여야 합니다.")
    return raw


def _parse_status(raw: object, path: str) -> EligibilityStatus:
    if not isinstance(raw, str):
        raise RuleSchemaError(f"{path}는 지원자격 상태 문자열이어야 합니다.")
    try:
        return EligibilityStatus(raw)
    except ValueError as error:
        raise RuleSchemaError(f"{path}에 허용되지 않은 지원자격 상태입니다: {raw}") from error


def _bounded_identifier(raw: object, path: str) -> str:
    if not isinstance(raw, str) or not IDENTIFIER_PATTERN.fullmatch(raw):
        raise RuleSchemaError(f"{path}는 소문자 snake_case 식별자여야 합니다.")
    return raw


def _reason_code(raw: object, path: str) -> str:
    if not isinstance(raw, str) or not REASON_CODE_PATTERN.fullmatch(raw):
        raise RuleSchemaError(f"{path}는 대문자 reason code여야 합니다.")
    return raw


def _require_exact_keys(value: Mapping[str, object], expected: set[str], path: str) -> None:
    keys = set(value)
    if keys != expected:
        raise RuleSchemaError(
            f"{path} 필드가 계약과 다릅니다. "
            f"expected={sorted(expected)}, actual={sorted(map(str, keys))}"
        )


def _validate_enum_fact(name: str, value: str | None, allowed: set[str]) -> None:
    if value is not None and value not in allowed:
        raise ValueError(f"{name}에 허용되지 않은 값입니다: {value}")


def _is_scalar(value: object) -> TypeGuard[Scalar]:
    return isinstance(value, (str, int, float, bool)) and not (
        isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")})
    )


def _is_number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


__all__ = [
    "ConditionOutcome",
    "ConditionTrace",
    "EligibilityDecision",
    "EligibilityRule",
    "EligibilityStatus",
    "EligibilityTrace",
    "RuleSchemaError",
    "ScoreCalculationBlocked",
    "StudentFacts",
    "UnusableEligibilityRule",
    "evaluate_eligibility",
    "require_score_calculation_allowed",
    "validate_eligibility_rule_payload",
]
