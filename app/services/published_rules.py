from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AdmissionEligibilityRule,
    DisqualificationRule,
    GradeSourceScopeRule,
    MultipleApplicationRule,
    ScoreRule,
)
from app.services.eligibility import (
    EligibilityDecision,
    EligibilityRule,
    StudentFacts,
    evaluate_eligibility,
)
from app.services.rule_admin import RuleAdministrationError, validate_rule_execution_contract


class PublishedRuleError(LookupError):
    pass


class PublishedRuleNotFound(PublishedRuleError):
    pass


class PublishedRuleConflict(PublishedRuleError):
    pass


@dataclass(frozen=True)
class PublishedRule:
    rule_id: str
    admission_track_id: str
    version: str
    lifecycle_status: str
    payload: dict[str, object]
    source_citation_id: str | None
    independent_verified: bool
    golden_test_ref: str | None
    human_approved_at: datetime | None


def load_published_eligibility_rule(session: Session, admission_track_id: str) -> PublishedRule:
    rows = session.scalars(
        select(AdmissionEligibilityRule).where(
            AdmissionEligibilityRule.admission_track_id == admission_track_id,
            AdmissionEligibilityRule.lifecycle_status == "PUBLISHED",
        )
    ).all()
    return _exactly_one(session, rows, admission_track_id, "지원자격")


def load_published_multiple_application_rule(
    session: Session, admission_track_id: str
) -> PublishedRule:
    rows = session.scalars(
        select(MultipleApplicationRule).where(
            MultipleApplicationRule.admission_track_id == admission_track_id,
            MultipleApplicationRule.lifecycle_status == "PUBLISHED",
        )
    ).all()
    return _exactly_one(session, rows, admission_track_id, "복수지원")


def load_published_disqualification_rule(
    session: Session, admission_track_id: str
) -> PublishedRule:
    rows = session.scalars(
        select(DisqualificationRule).where(
            DisqualificationRule.admission_track_id == admission_track_id,
            DisqualificationRule.lifecycle_status == "PUBLISHED",
        )
    ).all()
    return _exactly_one(session, rows, admission_track_id, "결격")


def load_published_grade_source_scope_rule(
    session: Session, admission_track_id: str
) -> PublishedRule:
    rows = session.scalars(
        select(GradeSourceScopeRule).where(
            GradeSourceScopeRule.admission_track_id == admission_track_id,
            GradeSourceScopeRule.lifecycle_status == "PUBLISHED",
        )
    ).all()
    return _exactly_one(session, rows, admission_track_id, "성적 출처 범위")


def load_published_score_rule(session: Session, admission_track_id: str) -> PublishedRule:
    rows = session.scalars(
        select(ScoreRule).where(
            ScoreRule.admission_track_id == admission_track_id,
            ScoreRule.lifecycle_status == "PUBLISHED",
        )
    ).all()
    return _exactly_one(session, rows, admission_track_id, "성적 계산")


def evaluate_published_eligibility(
    session: Session,
    admission_track_id: str,
    facts: StudentFacts,
) -> EligibilityDecision:
    stored_rule = load_published_eligibility_rule(session, admission_track_id)
    return evaluate_eligibility(facts, to_eligibility_rule(stored_rule))


def to_eligibility_rule(rule: PublishedRule) -> EligibilityRule:
    return EligibilityRule(
        rule_id=rule.rule_id,
        version=rule.version,
        lifecycle_status=rule.lifecycle_status,
        payload=deepcopy(rule.payload),
        source_citation_id=rule.source_citation_id,
        independent_verified=rule.independent_verified,
        golden_test_ref=rule.golden_test_ref,
        human_approved_at=rule.human_approved_at,
    )


def require_published_rule_usable(rule: PublishedRule) -> None:
    if rule.lifecycle_status != "PUBLISHED":
        raise PublishedRuleError("PUBLISHED 상태의 규칙만 실행할 수 있습니다.")
    if (
        not rule.source_citation_id
        or not rule.independent_verified
        or not rule.golden_test_ref
        or rule.human_approved_at is None
    ):
        raise PublishedRuleError(
            "근거·독립 검증·골든 테스트·사람 승인이 모두 있는 규칙만 실행할 수 있습니다."
        )


def _exactly_one(
    session: Session,
    rows: Sequence[
        AdmissionEligibilityRule
        | MultipleApplicationRule
        | DisqualificationRule
        | GradeSourceScopeRule
        | ScoreRule
    ],
    admission_track_id: str,
    rule_label: str,
) -> PublishedRule:
    if not rows:
        raise PublishedRuleNotFound(
            f"전형 {admission_track_id}에 게시된 {rule_label} 규칙이 없습니다."
        )
    if len(rows) > 1:
        raise PublishedRuleConflict(
            f"전형 {admission_track_id}에 게시된 {rule_label} 규칙이 둘 이상입니다."
        )
    row = rows[0]
    if row.admission_track_id is None:
        raise PublishedRuleError("전형이 연결되지 않은 규칙은 실행할 수 없습니다.")
    try:
        validate_rule_execution_contract(
            session,
            rule_type=_rule_type_for_row(row),
            rule=row,
        )
    except RuleAdministrationError as error:
        raise PublishedRuleError("게시 규칙의 무결성 검증에 실패했습니다.") from error
    rule = PublishedRule(
        rule_id=row.id,
        admission_track_id=row.admission_track_id,
        version=row.version,
        lifecycle_status=row.lifecycle_status,
        payload=deepcopy(row.rule_payload),
        source_citation_id=row.source_citation_id,
        independent_verified=row.independent_verified,
        golden_test_ref=row.golden_test_ref,
        human_approved_at=row.human_approved_at,
    )
    require_published_rule_usable(rule)
    return rule


def _rule_type_for_row(
    row: AdmissionEligibilityRule
    | MultipleApplicationRule
    | DisqualificationRule
    | GradeSourceScopeRule
    | ScoreRule,
) -> str:
    if isinstance(row, AdmissionEligibilityRule):
        return "ADMISSION_ELIGIBILITY_RULE"
    if isinstance(row, MultipleApplicationRule):
        return "MULTIPLE_APPLICATION_RULE"
    if isinstance(row, DisqualificationRule):
        return "DISQUALIFICATION_RULE"
    if isinstance(row, GradeSourceScopeRule):
        return "GRADE_SOURCE_SCOPE_RULE"
    if isinstance(row, ScoreRule):
        return "SCORE_RULE"
    raise PublishedRuleError("지원하지 않는 게시 규칙 유형입니다.")


__all__ = [
    "PublishedRule",
    "PublishedRuleConflict",
    "PublishedRuleError",
    "PublishedRuleNotFound",
    "evaluate_published_eligibility",
    "load_published_disqualification_rule",
    "load_published_eligibility_rule",
    "load_published_grade_source_scope_rule",
    "load_published_multiple_application_rule",
    "load_published_score_rule",
    "require_published_rule_usable",
    "to_eligibility_rule",
]
