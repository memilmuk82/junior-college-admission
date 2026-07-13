from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AdmissionEligibilityRule,
    DisqualificationRule,
    GradeSourceScopeRule,
    MultipleApplicationRule,
    RuleAuditEvent,
    RuleVersionLineage,
    ScoreRule,
)


class RuleAdministrationError(ValueError):
    pass


RULE_MODELS = {
    "ADMISSION_ELIGIBILITY_RULE": AdmissionEligibilityRule,
    "GRADE_SOURCE_SCOPE_RULE": GradeSourceScopeRule,
    "SCORE_RULE": ScoreRule,
    "MULTIPLE_APPLICATION_RULE": MultipleApplicationRule,
    "DISQUALIFICATION_RULE": DisqualificationRule,
}


@dataclass(frozen=True)
class PayloadChange:
    path: str
    before: object
    after: object


@dataclass(frozen=True)
class RuleImpact:
    sample_id: str
    before: Decimal
    after: Decimal
    delta: Decimal


@dataclass(frozen=True)
class HumanApproval:
    actor_ref: str
    approved_at: datetime
    confirmation: str


def compare_rule_payloads(
    before: Mapping[str, object], after: Mapping[str, object]
) -> tuple[PayloadChange, ...]:
    changes: list[PayloadChange] = []
    _compare_mapping("", before, after, changes)
    return tuple(changes)


def compare_rule_impact(
    before_payload: dict[str, object],
    after_payload: dict[str, object],
    samples: Sequence[dict[str, str]],
    evaluator: Callable[[dict[str, object], dict[str, str]], Decimal],
) -> tuple[RuleImpact, ...]:
    seen: set[str] = set()
    impacts: list[RuleImpact] = []
    for sample in samples:
        sample_id = sample.get("sample_id", "").strip()
        if not sample_id or not sample_id.startswith("synthetic-") or sample_id in seen:
            raise RuleAdministrationError(
                "영향도 표본은 중복 없는 synthetic sample ID가 필요합니다."
            )
        seen.add(sample_id)
        before = evaluator(before_payload, sample)
        after = evaluator(after_payload, sample)
        if not before.is_finite() or not after.is_finite():
            raise RuleAdministrationError("영향도 결과는 유한한 Decimal이어야 합니다.")
        impacts.append(RuleImpact(sample_id, before, after, after - before))
    if not impacts:
        raise RuleAdministrationError("영향도 비교에는 합성 표본이 필요합니다.")
    return tuple(impacts)


def clone_published_rule_as_draft(
    session: Session,
    *,
    rule_type: str,
    source_rule_id: str,
    new_version: str,
    actor_ref: str,
    change_reason: str,
    occurred_at: datetime,
) -> Any:
    model = _rule_model(rule_type)
    source = session.get(model, source_rule_id)
    if source is None or source.lifecycle_status != "PUBLISHED":
        raise RuleAdministrationError("게시 규칙만 새 DRAFT 버전으로 복제할 수 있습니다.")
    _validate_actor_and_time(actor_ref, occurred_at)
    if not new_version.strip() or not change_reason.strip():
        raise RuleAdministrationError("새 버전과 변경 사유가 필요합니다.")
    draft = model(
        admission_track_id=source.admission_track_id,
        version=new_version,
        lifecycle_status="DRAFT",
        rule_payload=copy.deepcopy(source.rule_payload),
        source_citation_id=source.source_citation_id,
        independent_verified=False,
        golden_test_ref=None,
        human_approved_at=None,
    )
    session.add(draft)
    session.flush()
    session.add(
        RuleVersionLineage(
            rule_type=rule_type,
            rule_id=draft.id,
            supersedes_rule_id=source.id,
            change_reason=change_reason,
        )
    )
    _audit(
        session,
        rule_type=rule_type,
        rule=draft,
        action="DRAFT_CLONED",
        actor_ref=actor_ref,
        occurred_at=occurred_at,
        before_payload=source.rule_payload,
        after_payload=draft.rule_payload,
        details={"source_rule_id": source.id, "change_reason": change_reason},
    )
    session.flush()
    return draft


def human_approve_tested_rule(
    session: Session, *, rule_type: str, rule_id: str, approval: HumanApproval
) -> Any:
    model = _rule_model(rule_type)
    rule = session.get(model, rule_id)
    if rule is None or rule.lifecycle_status != "TESTED":
        raise RuleAdministrationError("TESTED 규칙만 사람이 승인할 수 있습니다.")
    _validate_actor_and_time(approval.actor_ref, approval.approved_at)
    if approval.confirmation != "HUMAN_APPROVED":
        raise RuleAdministrationError("명시적 사람 승인 확인값이 필요합니다.")
    if not rule.source_citation_id or not rule.independent_verified or not rule.golden_test_ref:
        raise RuleAdministrationError("근거·독립 검증·골든 테스트가 모두 필요합니다.")
    rule.lifecycle_status = "HUMAN_APPROVED"
    rule.human_approved_at = approval.approved_at
    _audit(
        session,
        rule_type=rule_type,
        rule=rule,
        action="HUMAN_APPROVED",
        actor_ref=approval.actor_ref,
        occurred_at=approval.approved_at,
        before_payload=rule.rule_payload,
        after_payload=rule.rule_payload,
        details={},
    )
    session.flush()
    return rule


def publish_human_approved_rule(
    session: Session,
    *,
    rule_type: str,
    rule_id: str,
    actor_ref: str,
    occurred_at: datetime,
) -> Any:
    model = _rule_model(rule_type)
    rule = session.get(model, rule_id)
    if rule is None or rule.lifecycle_status != "HUMAN_APPROVED":
        raise RuleAdministrationError("사람 승인된 규칙만 게시할 수 있습니다.")
    _validate_actor_and_time(actor_ref, occurred_at)
    if not rule.admission_track_id:
        raise RuleAdministrationError("전형에 연결되지 않은 규칙은 게시할 수 없습니다.")
    current = session.scalar(
        select(model).where(
            model.admission_track_id == rule.admission_track_id,
            model.lifecycle_status == "PUBLISHED",
            model.id != rule.id,
        )
    )
    if current is not None:
        current.lifecycle_status = "SUPERSEDED"
        _audit(
            session,
            rule_type=rule_type,
            rule=current,
            action="SUPERSEDED",
            actor_ref=actor_ref,
            occurred_at=occurred_at,
            before_payload=current.rule_payload,
            after_payload=current.rule_payload,
            details={"replacement_rule_id": rule.id},
        )
        session.flush()
    rule.lifecycle_status = "PUBLISHED"
    _audit(
        session,
        rule_type=rule_type,
        rule=rule,
        action="PUBLISHED",
        actor_ref=actor_ref,
        occurred_at=occurred_at,
        before_payload=rule.rule_payload,
        after_payload=rule.rule_payload,
        details={"superseded_rule_id": None if current is None else current.id},
    )
    session.flush()
    return rule


def _compare_mapping(
    prefix: str,
    before: Mapping[str, object],
    after: Mapping[str, object],
    changes: list[PayloadChange],
) -> None:
    for key in sorted(set(before) | set(after)):
        path = f"{prefix}.{key}" if prefix else key
        before_value = before.get(key)
        after_value = after.get(key)
        if isinstance(before_value, Mapping) and isinstance(after_value, Mapping):
            _compare_mapping(path, before_value, after_value, changes)
        elif before_value != after_value:
            changes.append(PayloadChange(path, before_value, after_value))


def _rule_model(rule_type: str) -> Any:
    model = RULE_MODELS.get(rule_type)
    if model is None:
        raise RuleAdministrationError("지원하지 않는 규칙 유형입니다.")
    return model


def rule_model_for_type(rule_type: str) -> Any:
    return _rule_model(rule_type)


def _validate_actor_and_time(actor_ref: str, occurred_at: datetime) -> None:
    if not actor_ref.strip() or occurred_at.tzinfo is None:
        raise RuleAdministrationError("관리자 식별자와 timezone 포함 시각이 필요합니다.")


def _payload_digest(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _audit(
    session: Session,
    *,
    rule_type: str,
    rule: Any,
    action: str,
    actor_ref: str,
    occurred_at: datetime,
    before_payload: Mapping[str, object] | None,
    after_payload: Mapping[str, object] | None,
    details: dict[str, object],
) -> None:
    session.add(
        RuleAuditEvent(
            rule_type=rule_type,
            rule_id=rule.id,
            action=action,
            actor_ref=actor_ref,
            occurred_at=occurred_at,
            before_payload_digest=(
                None if before_payload is None else _payload_digest(before_payload)
            ),
            after_payload_digest=None if after_payload is None else _payload_digest(after_payload),
            details=details,
        )
    )


def record_rule_audit(
    session: Session,
    *,
    rule_type: str,
    rule: Any,
    action: str,
    actor_ref: str,
    occurred_at: datetime,
    before_payload: Mapping[str, object] | None,
    after_payload: Mapping[str, object] | None,
    details: dict[str, object],
) -> None:
    _validate_actor_and_time(actor_ref, occurred_at)
    _audit(
        session,
        rule_type=rule_type,
        rule=rule,
        action=action,
        actor_ref=actor_ref,
        occurred_at=occurred_at,
        before_payload=before_payload,
        after_payload=after_payload,
        details=details,
    )


__all__ = [
    "HumanApproval",
    "PayloadChange",
    "RuleAdministrationError",
    "RuleImpact",
    "clone_published_rule_as_draft",
    "compare_rule_impact",
    "compare_rule_payloads",
    "human_approve_tested_rule",
    "publish_human_approved_rule",
    "record_rule_audit",
    "rule_model_for_type",
]
