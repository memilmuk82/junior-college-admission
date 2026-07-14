from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AdmissionEligibilityRule,
    AdmissionRound,
    AdmissionTrack,
    Campus,
    DisqualificationRule,
    GradeSourceScopeRule,
    Institution,
    MultipleApplicationRule,
    Program,
    RuleAuditEvent,
    RuleGoldenTestArtifact,
    RuleReview,
    RuleVersionLineage,
    ScoreRule,
    SourceCitation,
    SourceDocument,
    SourceDocumentPage,
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


@dataclass(frozen=True)
class RuleExtractionEvidence:
    actor_ref: str
    extracted_at: datetime
    confirmation: str


@dataclass(frozen=True)
class RuleVerificationEvidence:
    actor_ref: str
    verified_at: datetime
    confirmation: str
    independent_review_id: str


@dataclass(frozen=True)
class RuleTestEvidence:
    actor_ref: str
    tested_at: datetime
    confirmation: str
    golden_test_ref: str
    independent_review_id: str


@dataclass(frozen=True)
class GoldenTestRunEvidence:
    runner_ref: str
    executed_at: datetime
    suite_ref: str
    suite_digest: str
    independent_review_id: str
    case_count: int
    passed_case_count: int
    failed_case_count: int


OFFICIAL_DOCUMENT_TYPES = {
    "AMENDED_FINAL_GUIDE",
    "FINAL_GUIDE",
    "AMENDED_IMPLEMENTATION_PLAN",
    "IMPLEMENTATION_PLAN",
}

RULE_CONTRACT_SCHEMA_VERSION = 2


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
        golden_test_rule_type=None,
        human_approved_at=None,
    )
    if isinstance(source, ScoreRule):
        for attribute in (
            "admission_year",
            "university_code",
            "university_name",
            "campus_code",
            "admission_round",
            "admission_track_code",
            "admission_track_name",
            "evidence_document_ref",
            "evidence_page",
            "evidence_location",
            "source_status",
            "change_reason",
            "administrator_note",
        ):
            setattr(draft, attribute, copy.deepcopy(getattr(source, attribute)))
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
    validate_rule_publication_source(session, rule)
    _validate_rule_payload(rule_type, rule.rule_payload)
    _validate_tested_evidence(
        session,
        rule_type=rule_type,
        rule=rule,
        occurred_at=approval.approved_at,
    )
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
    validate_rule_publication_source(session, rule)
    _validate_rule_payload(rule_type, rule.rule_payload)
    _validate_tested_evidence(
        session,
        rule_type=rule_type,
        rule=rule,
        occurred_at=rule.human_approved_at,
    )
    audit_chain = _validate_audit_chain(
        session, rule_type=rule_type, rule=rule, through="HUMAN_APPROVED", occurred_at=occurred_at
    )
    human_event = audit_chain["HUMAN_APPROVED"]
    if rule.human_approved_at is None or rule.human_approved_at > occurred_at:
        raise RuleAdministrationError("사람 승인 이후 시각에만 게시할 수 있습니다.")
    if human_event.occurred_at != rule.human_approved_at:
        raise RuleAdministrationError("사람 승인 시각과 감사 증거가 일치하지 않습니다.")
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


def mark_rule_extracted(
    session: Session,
    *,
    rule_type: str,
    rule_id: str,
    evidence: RuleExtractionEvidence,
) -> Any:
    model = _rule_model(rule_type)
    rule = session.get(model, rule_id)
    if rule is None or rule.lifecycle_status != "DRAFT":
        raise RuleAdministrationError("DRAFT 규칙만 EXTRACTED 상태로 기록할 수 있습니다.")
    _validate_actor_and_time(evidence.actor_ref, evidence.extracted_at)
    if evidence.confirmation != "EXTRACTED":
        raise RuleAdministrationError("명시적 EXTRACTED 확인값이 필요합니다.")
    if not rule.admission_track_id or not rule.source_citation_id:
        raise RuleAdministrationError("전형과 근거 citation이 연결된 DRAFT가 필요합니다.")
    _validate_rule_payload(rule_type, rule.rule_payload)
    rule.lifecycle_status = "EXTRACTED"
    rule.independent_verified = False
    rule.golden_test_ref = None
    rule.golden_test_rule_type = None
    rule.human_approved_at = None
    _audit(
        session,
        rule_type=rule_type,
        rule=rule,
        action="EXTRACTED",
        actor_ref=evidence.actor_ref,
        occurred_at=evidence.extracted_at,
        before_payload=rule.rule_payload,
        after_payload=rule.rule_payload,
        details={},
    )
    session.flush()
    return rule


def verify_extracted_rule(
    session: Session,
    *,
    rule_type: str,
    rule_id: str,
    evidence: RuleVerificationEvidence,
) -> Any:
    model = _rule_model(rule_type)
    rule = session.get(model, rule_id)
    if rule is None or rule.lifecycle_status != "EXTRACTED":
        raise RuleAdministrationError("EXTRACTED 규칙만 VERIFIED 상태로 기록할 수 있습니다.")
    _validate_actor_and_time(evidence.actor_ref, evidence.verified_at)
    if evidence.confirmation != "VERIFIED":
        raise RuleAdministrationError("명시적 VERIFIED 확인값이 필요합니다.")
    _validate_audit_chain(
        session,
        rule_type=rule_type,
        rule=rule,
        through="EXTRACTED",
        occurred_at=evidence.verified_at,
    )
    review = _approved_independent_review(
        session,
        rule_type=rule_type,
        rule=rule,
        review_id=evidence.independent_review_id,
        actor_ref=evidence.actor_ref,
        occurred_at=evidence.verified_at,
    )
    validate_rule_publication_source(session, rule)
    _validate_rule_payload(rule_type, rule.rule_payload)
    rule.lifecycle_status = "VERIFIED"
    rule.independent_verified = True
    rule.golden_test_ref = None
    rule.golden_test_rule_type = None
    rule.human_approved_at = None
    _audit(
        session,
        rule_type=rule_type,
        rule=rule,
        action="VERIFIED",
        actor_ref=evidence.actor_ref,
        occurred_at=evidence.verified_at,
        before_payload=rule.rule_payload,
        after_payload=rule.rule_payload,
        details={
            "independent_review_id": review.id,
            "independent_reviewer_ref": review.reviewer_ref,
        },
    )
    session.flush()
    return rule


def record_golden_test_artifact(
    session: Session,
    *,
    rule_type: str,
    rule_id: str,
    evidence: GoldenTestRunEvidence,
) -> RuleGoldenTestArtifact:
    model = _rule_model(rule_type)
    rule = session.get(model, rule_id)
    if rule is None or rule.lifecycle_status != "VERIFIED":
        raise RuleAdministrationError(
            "VERIFIED 규칙에 대해서만 골든 테스트 실행 증거를 기록할 수 있습니다."
        )
    if evidence.executed_at.tzinfo is None:
        raise RuleAdministrationError("골든 테스트 실행 시각에는 timezone 정보가 필요합니다.")
    runner_ref = _safe_reference(
        evidence.runner_ref,
        maximum_length=120,
        error_message="안전한 골든 테스트 runner 참조가 필요합니다.",
    )
    suite_ref = _safe_reference(
        evidence.suite_ref,
        maximum_length=240,
        error_message="안전한 골든 테스트 suite 참조가 필요합니다.",
    )
    if not _is_sha256_digest(evidence.suite_digest):
        raise RuleAdministrationError("골든 테스트 suite digest는 SHA-256이어야 합니다.")
    counts = (
        evidence.case_count,
        evidence.passed_case_count,
        evidence.failed_case_count,
    )
    if (
        any(isinstance(value, bool) or not isinstance(value, int) for value in counts)
        or evidence.case_count <= 0
        or evidence.passed_case_count < 0
        or evidence.failed_case_count < 0
        or evidence.passed_case_count + evidence.failed_case_count != evidence.case_count
    ):
        raise RuleAdministrationError("골든 테스트 case 집계가 일치하지 않습니다.")

    review = _validate_independent_verification(session, rule_type=rule_type, rule=rule)
    if review.id != evidence.independent_review_id:
        raise RuleAdministrationError("VERIFIED 단계와 같은 독립 검수 기록이 필요합니다.")
    _validate_audit_chain(
        session,
        rule_type=rule_type,
        rule=rule,
        through="VERIFIED",
        occurred_at=evidence.executed_at,
    )
    validate_rule_publication_source(session, rule)
    _validate_rule_payload(rule_type, rule.rule_payload)

    artifact_id = str(uuid4())
    result_status = "PASSED" if evidence.failed_case_count == 0 else "FAILED"
    artifact = RuleGoldenTestArtifact(
        id=artifact_id,
        rule_type=rule_type,
        rule_id=rule.id,
        independent_review_id=review.id,
        artifact_ref=f"golden-run/{rule_type}/{artifact_id}",
        artifact_digest="0" * 64,
        payload_digest=_payload_digest(rule.rule_payload),
        contract_digest=_contract_digest(session, rule_type, rule),
        contract_schema_version=RULE_CONTRACT_SCHEMA_VERSION,
        suite_ref=suite_ref,
        suite_digest=evidence.suite_digest,
        result_status=result_status,
        case_count=evidence.case_count,
        passed_case_count=evidence.passed_case_count,
        failed_case_count=evidence.failed_case_count,
        runner_ref=runner_ref,
        executed_at=evidence.executed_at,
    )
    artifact.artifact_digest = _golden_artifact_digest(artifact)
    session.add(artifact)
    session.flush()
    return artifact


def mark_rule_tested(
    session: Session,
    *,
    rule_type: str,
    rule_id: str,
    evidence: RuleTestEvidence,
) -> Any:
    model = _rule_model(rule_type)
    rule = session.get(model, rule_id)
    if rule is None or rule.lifecycle_status != "VERIFIED":
        raise RuleAdministrationError("VERIFIED 규칙만 TESTED 상태로 기록할 수 있습니다.")
    _validate_actor_and_time(evidence.actor_ref, evidence.tested_at)
    if evidence.confirmation != "TESTED":
        raise RuleAdministrationError("명시적 TESTED 확인값이 필요합니다.")
    golden_test_ref = _safe_reference(
        evidence.golden_test_ref,
        maximum_length=240,
        error_message="안전한 골든 테스트 참조가 필요합니다.",
    )
    review = _approved_independent_review(
        session,
        rule_type=rule_type,
        rule=rule,
        review_id=evidence.independent_review_id,
        actor_ref=evidence.actor_ref,
        occurred_at=evidence.tested_at,
    )
    verified_review = _validate_independent_verification(session, rule_type=rule_type, rule=rule)
    _validate_audit_chain(
        session,
        rule_type=rule_type,
        rule=rule,
        through="VERIFIED",
        occurred_at=evidence.tested_at,
    )
    if review.id != verified_review.id:
        raise RuleAdministrationError("VERIFIED 단계와 같은 독립 검수 기록이 필요합니다.")
    validate_rule_publication_source(session, rule)
    _validate_rule_payload(rule_type, rule.rule_payload)
    artifact = _validate_golden_artifact(
        session,
        rule_type=rule_type,
        rule=rule,
        artifact_ref=golden_test_ref,
        review=review,
        occurred_at=evidence.tested_at,
        require_rule_binding=False,
    )
    rule.lifecycle_status = "TESTED"
    rule.independent_verified = True
    rule.golden_test_ref = golden_test_ref
    rule.golden_test_rule_type = rule_type
    rule.human_approved_at = None
    _audit(
        session,
        rule_type=rule_type,
        rule=rule,
        action="TESTED",
        actor_ref=evidence.actor_ref,
        occurred_at=evidence.tested_at,
        before_payload=rule.rule_payload,
        after_payload=rule.rule_payload,
        details={
            "golden_test_ref": golden_test_ref,
            "golden_artifact_id": artifact.id,
            "golden_artifact_digest": artifact.artifact_digest,
            "golden_artifact_runner_ref": artifact.runner_ref,
            "golden_artifact_suite_ref": artifact.suite_ref,
            "golden_artifact_suite_digest": artifact.suite_digest,
            "golden_artifact_case_count": artifact.case_count,
            "independent_review_id": review.id,
            "independent_reviewer_ref": review.reviewer_ref,
        },
    )
    session.flush()
    return rule


def validate_rule_publication_source(session: Session, rule: Any) -> SourceDocument:
    if not rule.admission_track_id:
        raise RuleAdministrationError("전형에 연결되지 않은 규칙은 검수·게시할 수 없습니다.")
    track = session.get(AdmissionTrack, rule.admission_track_id)
    if track is None:
        raise RuleAdministrationError("규칙에 연결된 전형을 확인할 수 없습니다.")
    admission_round = session.get(AdmissionRound, track.admission_round_id)
    program = session.get(Program, track.program_id)
    if admission_round is None or program is None:
        raise RuleAdministrationError("전형의 모집시기·모집단위 연결을 확인할 수 없습니다.")
    campus = session.get(Campus, program.campus_id)
    if campus is None:
        raise RuleAdministrationError("전형의 캠퍼스 연결을 확인할 수 없습니다.")
    if campus.institution_id != admission_round.institution_id:
        raise RuleAdministrationError("전형의 모집시기와 캠퍼스 대학이 일치하지 않습니다.")
    institution = session.get(Institution, admission_round.institution_id)
    if institution is None:
        raise RuleAdministrationError("전형의 대학 연결을 확인할 수 없습니다.")

    if not rule.source_citation_id:
        raise RuleAdministrationError("규칙의 공식 근거 citation이 필요합니다.")
    citation = session.get(SourceCitation, rule.source_citation_id)
    if citation is None:
        raise RuleAdministrationError("규칙의 근거 citation을 확인할 수 없습니다.")
    document = session.get(SourceDocument, citation.source_document_id)
    if document is None:
        raise RuleAdministrationError("citation의 근거 문서를 확인할 수 없습니다.")

    if document.document_status not in {"HUMAN_APPROVED", "PUBLISHED"}:
        raise RuleAdministrationError("사람 검수된 근거 문서만 규칙에 사용할 수 있습니다.")
    if (
        document.verification_status != "HUMAN_APPROVED"
        or document.year_consistency_status != "CONSISTENT"
        or document.detected_years != [document.academic_year]
    ):
        raise RuleAdministrationError("근거 문서의 학년도 일관성과 사람 검증이 필요합니다.")
    if document.academic_year != admission_round.academic_year:
        raise RuleAdministrationError("근거 문서와 전형의 모집학년도가 일치하지 않습니다.")
    if document.institution_id is not None and (
        document.institution_id != admission_round.institution_id
        or document.institution_id != campus.institution_id
    ):
        raise RuleAdministrationError("근거 문서와 전형의 대학이 일치하지 않습니다.")
    if document.campus_id is not None and document.campus_id != campus.id:
        raise RuleAdministrationError("근거 문서와 전형의 캠퍼스가 일치하지 않습니다.")
    if citation.page_number > document.page_count:
        raise RuleAdministrationError("citation 페이지가 근거 문서 범위를 벗어났습니다.")
    if not citation.locator or not citation.locator.strip():
        raise RuleAdministrationError("citation의 표·문단 위치가 필요합니다.")

    if citation.source_document_page_id is None:
        raise RuleAdministrationError("사람 검수된 citation 페이지 기록이 필요합니다.")
    page = session.get(SourceDocumentPage, citation.source_document_page_id)
    if (
        page is None
        or page.source_document_id != document.id
        or page.page_number != citation.page_number
        or page.detected_academic_year != document.academic_year
        or page.verification_status != "HUMAN_APPROVED"
    ):
        raise RuleAdministrationError("citation의 페이지 검증 정보가 일치하지 않습니다.")

    rule_year = getattr(rule, "admission_year", None)
    if rule_year is not None and rule_year != admission_round.academic_year:
        raise RuleAdministrationError("규칙 업무키와 전형의 모집학년도가 일치하지 않습니다.")
    rule_round = getattr(rule, "admission_round", None)
    if rule_round is not None and rule_round != admission_round.code:
        raise RuleAdministrationError("규칙 업무키와 모집시기 코드가 일치하지 않습니다.")
    rule_track = getattr(rule, "admission_track_code", None)
    if rule_track is not None and rule_track != track.code:
        raise RuleAdministrationError("규칙 업무키와 전형 코드가 일치하지 않습니다.")
    rule_track_name = getattr(rule, "admission_track_name", None)
    if rule_track_name is not None and rule_track_name != track.name:
        raise RuleAdministrationError("규칙 업무키와 전형명이 일치하지 않습니다.")
    university_name = getattr(rule, "university_name", None)
    if university_name is not None and university_name != institution.name:
        raise RuleAdministrationError("규칙 업무키와 대학명이 일치하지 않습니다.")
    evidence_document_ref = getattr(rule, "evidence_document_ref", None)
    if evidence_document_ref is not None and evidence_document_ref != document.id:
        raise RuleAdministrationError("규칙의 근거 문서 참조와 citation이 일치하지 않습니다.")
    evidence_page = getattr(rule, "evidence_page", None)
    if evidence_page is not None and evidence_page != citation.page_number:
        raise RuleAdministrationError("규칙의 근거 페이지와 citation이 일치하지 않습니다.")
    evidence_location = getattr(rule, "evidence_location", None)
    if evidence_location is not None and evidence_location != citation.locator:
        raise RuleAdministrationError("규칙의 근거 위치와 citation이 일치하지 않습니다.")
    source_status = getattr(rule, "source_status", None)
    if source_status is not None and source_status != document.document_type:
        raise RuleAdministrationError("규칙의 출처 상태와 근거 문서 유형이 일치하지 않습니다.")
    if isinstance(rule, ScoreRule) and any(
        value is None
        for value in (
            rule.admission_year,
            rule.university_code,
            rule.university_name,
            rule.campus_code,
            rule.admission_round,
            rule.admission_track_code,
            rule.admission_track_name,
            rule.evidence_document_ref,
            rule.evidence_page,
            rule.evidence_location,
            rule.source_status,
        )
    ):
        raise RuleAdministrationError("성적 규칙의 업무키와 근거 메타데이터가 필요합니다.")
    if isinstance(rule, ScoreRule) and (
        institution.code is None
        or not institution.code.strip()
        or rule.university_code != institution.code
    ):
        raise RuleAdministrationError("성적 규칙의 대학 코드가 canonical 대학과 일치하지 않습니다.")
    if isinstance(rule, ScoreRule) and (
        campus.code is None or not campus.code.strip() or rule.campus_code != campus.code
    ):
        raise RuleAdministrationError(
            "성적 규칙의 캠퍼스 코드가 canonical 캠퍼스와 일치하지 않습니다."
        )

    payload = rule.rule_payload if isinstance(rule.rule_payload, Mapping) else {}
    payload_source_status = payload.get("source_status")
    if payload_source_status is not None and payload_source_status != document.document_type:
        raise RuleAdministrationError("규칙 payload의 출처 상태가 근거 문서와 일치하지 않습니다.")
    evidence_level = payload.get("evidence_level")
    if document.document_type not in OFFICIAL_DOCUMENT_TYPES | {
        "COMMON_STANDARD",
        "VERIFIED_REFERENCE",
        "REFERENCE_ONLY",
        "AI_EXTRACTED_DRAFT",
        "MANUAL_REVIEW",
    }:
        raise RuleAdministrationError("허용되지 않은 근거 문서 유형입니다.")
    if document.document_type in {"REFERENCE_ONLY", "AI_EXTRACTED_DRAFT", "MANUAL_REVIEW"}:
        raise RuleAdministrationError("검수·게시할 수 없는 근거 문서 상태입니다.")
    if evidence_level is not None:
        expected_document_types = {
            "UNIVERSITY_OFFICIAL": OFFICIAL_DOCUMENT_TYPES,
            "COMMON_OFFICIAL": {"COMMON_STANDARD"},
            "VERIFIED_REFERENCE": {"VERIFIED_REFERENCE"},
            "INTERNAL_CALCULATION": {"VERIFIED_REFERENCE"},
            "MANUAL_REVIEW": set(),
        }
        if evidence_level not in expected_document_types:
            raise RuleAdministrationError("허용되지 않은 규칙 근거 수준입니다.")
        if document.document_type not in expected_document_types[evidence_level]:
            raise RuleAdministrationError("규칙 근거 수준과 문서 유형이 일치하지 않습니다.")
        if evidence_level == "UNIVERSITY_OFFICIAL" and (
            document.institution_id != admission_round.institution_id
        ):
            raise RuleAdministrationError("대학 공식 규칙에는 해당 대학의 공식 문서가 필요합니다.")
    return document


def validate_rule_execution_contract(
    session: Session,
    *,
    rule_type: str,
    rule: Any,
) -> None:
    if rule.lifecycle_status != "PUBLISHED":
        raise RuleAdministrationError("PUBLISHED 규칙만 실행할 수 있습니다.")
    validate_rule_publication_source(session, rule)
    _validate_rule_payload(rule_type, rule.rule_payload)
    tested_event = _validate_tested_evidence(
        session,
        rule_type=rule_type,
        rule=rule,
        occurred_at=rule.human_approved_at,
    )
    audit_chain = _validate_audit_chain(
        session,
        rule_type=rule_type,
        rule=rule,
        through="PUBLISHED",
        occurred_at=None,
    )
    human_event = audit_chain["HUMAN_APPROVED"]
    published_event = audit_chain["PUBLISHED"]
    if (
        rule.human_approved_at is None
        or human_event.occurred_at != rule.human_approved_at
        or human_event.occurred_at < tested_event.occurred_at
        or published_event.occurred_at < human_event.occurred_at
    ):
        raise RuleAdministrationError("게시 규칙의 감사 시각 순서가 일치하지 않습니다.")


def _approved_independent_review(
    session: Session,
    *,
    rule_type: str,
    rule: Any,
    review_id: str,
    actor_ref: str,
    occurred_at: datetime,
) -> RuleReview:
    review = session.get(RuleReview, review_id)
    if (
        review is None
        or review.rule_type != rule_type
        or review.rule_id != rule.id
        or review.review_kind != "INDEPENDENT_VERIFICATION"
        or review.review_status != "APPROVED"
        or review.reviewed_at is None
        or review.reviewed_at.tzinfo is None
        or review.reviewed_at > occurred_at
        or not review.reviewer_ref.strip()
        or review.reviewer_ref.strip() == actor_ref.strip()
    ):
        raise RuleAdministrationError("별도 검수자가 승인한 독립 검수 기록이 필요합니다.")
    if review.payload_digest != _payload_digest(rule.rule_payload):
        raise RuleAdministrationError("현재 payload에 결속된 독립 검수 기록이 필요합니다.")
    if review.contract_digest != _contract_digest(session, rule_type, rule):
        raise RuleAdministrationError("현재 규칙·근거에 결속된 독립 검수 기록이 필요합니다.")
    if review.contract_schema_version != RULE_CONTRACT_SCHEMA_VERSION:
        raise RuleAdministrationError("현재 계약 버전에 결속된 독립 검수 기록이 필요합니다.")
    creator = session.scalar(
        select(RuleAuditEvent)
        .where(
            RuleAuditEvent.rule_type == rule_type,
            RuleAuditEvent.rule_id == rule.id,
            RuleAuditEvent.action.in_(("DRAFT_CREATED", "DRAFT_CLONED")),
        )
        .order_by(
            RuleAuditEvent.occurred_at,
            RuleAuditEvent.created_at,
            RuleAuditEvent.id,
        )
        .limit(1)
    )
    if creator is not None and review.reviewer_ref.strip() == creator.actor_ref.strip():
        raise RuleAdministrationError("규칙 작성자와 다른 독립 검수자가 필요합니다.")
    return review


def _validate_independent_verification(
    session: Session,
    *,
    rule_type: str,
    rule: Any,
) -> RuleReview:
    if not rule.independent_verified:
        raise RuleAdministrationError("독립 검증이 완료된 규칙이 필요합니다.")
    event = session.scalar(
        select(RuleAuditEvent)
        .where(
            RuleAuditEvent.rule_type == rule_type,
            RuleAuditEvent.rule_id == rule.id,
            RuleAuditEvent.action == "VERIFIED",
        )
        .order_by(
            RuleAuditEvent.occurred_at.desc(),
            RuleAuditEvent.created_at.desc(),
            RuleAuditEvent.id.desc(),
        )
        .limit(1)
    )
    review_id = None if event is None else event.details.get("independent_review_id")
    reviewer_ref = None if event is None else event.details.get("independent_reviewer_ref")
    if (
        event is None
        or event.after_payload_digest != _payload_digest(rule.rule_payload)
        or event.details.get("contract_digest") != _contract_digest(session, rule_type, rule)
        or event.details.get("contract_schema_version") != RULE_CONTRACT_SCHEMA_VERSION
        or not isinstance(review_id, str)
        or not isinstance(reviewer_ref, str)
    ):
        raise RuleAdministrationError("현재 payload에 결속된 독립 검수 증거가 필요합니다.")
    review = session.get(RuleReview, review_id)
    if (
        review is None
        or review.rule_type != rule_type
        or review.rule_id != rule.id
        or review.review_kind != "INDEPENDENT_VERIFICATION"
        or review.review_status != "APPROVED"
        or review.reviewed_at is None
        or review.reviewed_at.tzinfo is None
        or review.reviewed_at > event.occurred_at
        or review.reviewer_ref != reviewer_ref
        or review.reviewer_ref.strip() == event.actor_ref.strip()
        or review.payload_digest != event.after_payload_digest
        or review.contract_digest != event.details.get("contract_digest")
        or review.contract_schema_version != event.details.get("contract_schema_version")
    ):
        raise RuleAdministrationError("독립 검수 기록이 취소·변경되었거나 일치하지 않습니다.")
    return review


def _validate_preceding_audit(
    session: Session,
    *,
    rule_type: str,
    rule: Any,
    action: str,
    occurred_at: datetime | None,
) -> RuleAuditEvent:
    event = session.scalar(
        select(RuleAuditEvent)
        .where(
            RuleAuditEvent.rule_type == rule_type,
            RuleAuditEvent.rule_id == rule.id,
            RuleAuditEvent.action == action,
        )
        .order_by(
            RuleAuditEvent.occurred_at.desc(),
            RuleAuditEvent.created_at.desc(),
            RuleAuditEvent.id.desc(),
        )
        .limit(1)
    )
    if (
        event is None
        or event.after_payload_digest != _payload_digest(rule.rule_payload)
        or event.details.get("contract_digest") != _contract_digest(session, rule_type, rule)
        or event.details.get("contract_schema_version") != RULE_CONTRACT_SCHEMA_VERSION
        or (occurred_at is not None and event.occurred_at > occurred_at)
    ):
        raise RuleAdministrationError(f"현재 규칙·근거에 결속된 {action} 감사 증거가 필요합니다.")
    return event


_AUDIT_LIFECYCLE = (
    "EXTRACTED",
    "VERIFIED",
    "TESTED",
    "HUMAN_APPROVED",
    "PUBLISHED",
)


def _validate_audit_chain(
    session: Session,
    *,
    rule_type: str,
    rule: Any,
    through: str,
    occurred_at: datetime | None,
) -> dict[str, RuleAuditEvent]:
    try:
        final_index = _AUDIT_LIFECYCLE.index(through)
    except ValueError as error:
        raise RuleAdministrationError("지원하지 않는 감사 생명주기 단계입니다.") from error
    events: dict[str, RuleAuditEvent] = {}
    previous: RuleAuditEvent | None = None
    for action in _AUDIT_LIFECYCLE[: final_index + 1]:
        event = _validate_preceding_audit(
            session,
            rule_type=rule_type,
            rule=rule,
            action=action,
            occurred_at=occurred_at,
        )
        if previous is not None and event.occurred_at < previous.occurred_at:
            raise RuleAdministrationError("규칙 감사 생명주기의 시각 순서가 일치하지 않습니다.")
        events[action] = event
        previous = event
    return events


def _validate_tested_evidence(
    session: Session,
    *,
    rule_type: str,
    rule: Any,
    occurred_at: datetime | None,
) -> RuleAuditEvent:
    review = _validate_independent_verification(session, rule_type=rule_type, rule=rule)
    events = _validate_audit_chain(
        session,
        rule_type=rule_type,
        rule=rule,
        through="TESTED",
        occurred_at=occurred_at,
    )
    tested_event = events["TESTED"]
    artifact_ref = rule.golden_test_ref or ""
    artifact = _validate_golden_artifact(
        session,
        rule_type=rule_type,
        rule=rule,
        artifact_ref=artifact_ref,
        review=review,
        occurred_at=tested_event.occurred_at,
    )
    if (
        tested_event.details.get("golden_test_ref") != rule.golden_test_ref
        or tested_event.details.get("golden_artifact_id") != artifact.id
        or tested_event.details.get("golden_artifact_digest") != artifact.artifact_digest
        or tested_event.details.get("golden_artifact_runner_ref") != artifact.runner_ref
        or tested_event.details.get("golden_artifact_suite_ref") != artifact.suite_ref
        or tested_event.details.get("golden_artifact_suite_digest") != artifact.suite_digest
        or tested_event.details.get("golden_artifact_case_count") != artifact.case_count
        or tested_event.details.get("independent_review_id") != review.id
        or tested_event.details.get("independent_reviewer_ref") != review.reviewer_ref
    ):
        raise RuleAdministrationError(
            "현재 골든 테스트와 VERIFIED 검수에 결속된 TESTED 증거가 필요합니다."
        )
    return tested_event


def _validate_golden_artifact(
    session: Session,
    *,
    rule_type: str,
    rule: Any,
    artifact_ref: str,
    review: RuleReview,
    occurred_at: datetime,
    require_rule_binding: bool = True,
) -> RuleGoldenTestArtifact:
    artifact = session.scalar(
        select(RuleGoldenTestArtifact).where(RuleGoldenTestArtifact.artifact_ref == artifact_ref)
    )
    if (
        artifact is None
        or (
            require_rule_binding
            and (rule.golden_test_ref != artifact_ref or rule.golden_test_rule_type != rule_type)
        )
        or artifact.rule_type != rule_type
        or artifact.rule_id != rule.id
        or artifact.independent_review_id != review.id
        or artifact.result_status != "PASSED"
        or not _is_sha256_digest(artifact.artifact_digest)
        or not _is_sha256_digest(artifact.payload_digest)
        or not _is_sha256_digest(artifact.contract_digest)
        or not _is_sha256_digest(artifact.suite_digest)
        or not _is_safe_reference(artifact.artifact_ref, maximum_length=240)
        or not _is_safe_reference(artifact.suite_ref, maximum_length=240)
        or not _is_safe_reference(artifact.runner_ref, maximum_length=120)
        or artifact.executed_at.tzinfo is None
        or artifact.executed_at > occurred_at
        or artifact.case_count <= 0
        or artifact.passed_case_count != artifact.case_count
        or artifact.failed_case_count != 0
        or artifact.passed_case_count + artifact.failed_case_count != artifact.case_count
        or artifact.payload_digest != _payload_digest(rule.rule_payload)
        or artifact.contract_digest != _contract_digest(session, rule_type, rule)
        or artifact.contract_schema_version != RULE_CONTRACT_SCHEMA_VERSION
        or artifact.artifact_digest != _golden_artifact_digest(artifact)
    ):
        raise RuleAdministrationError(
            "현재 규칙·검수·근거에 결속된 PASSED 골든 테스트 artifact가 필요합니다."
        )
    return artifact


def _validate_rule_payload(rule_type: str, payload: Mapping[str, object]) -> None:
    try:
        if rule_type == "ADMISSION_ELIGIBILITY_RULE":
            from app.services.eligibility import validate_eligibility_rule_payload

            validate_eligibility_rule_payload(payload)
        elif rule_type == "GRADE_SOURCE_SCOPE_RULE":
            from app.services.score_inputs import validate_grade_source_scope_payload

            validate_grade_source_scope_payload(dict(payload))
        elif rule_type == "SCORE_RULE":
            from app.services.score_rule_schema import validate_score_rule_payload

            validate_score_rule_payload(payload)
        elif rule_type == "MULTIPLE_APPLICATION_RULE":
            from app.services.application_policies import (
                validate_multiple_application_rule_payload,
            )

            validate_multiple_application_rule_payload(payload)
        elif rule_type == "DISQUALIFICATION_RULE":
            from app.services.application_policies import validate_disqualification_rule_payload

            validate_disqualification_rule_payload(payload)
        else:
            raise RuleAdministrationError("지원하지 않는 규칙 유형입니다.")
    except RuleAdministrationError:
        raise
    except (TypeError, ValueError) as error:
        raise RuleAdministrationError(
            "규칙 payload가 제한형 DSL 계약과 일치하지 않습니다."
        ) from error


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


def _is_safe_reference(value: object, *, maximum_length: int) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= maximum_length
        and ".." not in value
        and not any(ord(character) < 32 or ord(character) == 127 for character in value)
    )


def _safe_reference(value: object, *, maximum_length: int, error_message: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if not _is_safe_reference(normalized, maximum_length=maximum_length):
        raise RuleAdministrationError(error_message)
    return normalized


def _is_sha256_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _payload_digest(payload: Mapping[str, object]) -> str:
    return _canonical_digest(payload)


def rule_payload_digest(payload: Mapping[str, object]) -> str:
    return _payload_digest(payload)


def _canonical_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        raise RuleAdministrationError("규칙 근거 시각에는 timezone 정보가 필요합니다.")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _golden_artifact_digest(artifact: RuleGoldenTestArtifact) -> str:
    return _canonical_digest(
        {
            "artifact_schema_version": 1,
            "artifact_id": artifact.id,
            "artifact_ref": artifact.artifact_ref,
            "rule_type": artifact.rule_type,
            "rule_id": artifact.rule_id,
            "independent_review_id": artifact.independent_review_id,
            "payload_digest": artifact.payload_digest,
            "contract_digest": artifact.contract_digest,
            "contract_schema_version": artifact.contract_schema_version,
            "suite_ref": artifact.suite_ref,
            "suite_digest": artifact.suite_digest,
            "result_status": artifact.result_status,
            "case_count": artifact.case_count,
            "passed_case_count": artifact.passed_case_count,
            "failed_case_count": artifact.failed_case_count,
            "runner_ref": artifact.runner_ref,
            "executed_at": _canonical_datetime(artifact.executed_at),
        }
    )


def _contract_digest(session: Session, rule_type: str, rule: Any) -> str:
    citation = (
        None
        if not rule.source_citation_id
        else session.get(SourceCitation, rule.source_citation_id)
    )
    document = (
        None if citation is None else session.get(SourceDocument, citation.source_document_id)
    )
    page = (
        None
        if citation is None or citation.source_document_page_id is None
        else session.get(SourceDocumentPage, citation.source_document_page_id)
    )
    track = (
        None
        if not rule.admission_track_id
        else session.get(AdmissionTrack, rule.admission_track_id)
    )
    admission_round = (
        None if track is None else session.get(AdmissionRound, track.admission_round_id)
    )
    program = None if track is None else session.get(Program, track.program_id)
    campus = None if program is None else session.get(Campus, program.campus_id)
    institution = (
        None
        if admission_round is None
        else session.get(Institution, admission_round.institution_id)
    )

    rule_snapshot = {
        "id": rule.id,
        "admission_track_id": rule.admission_track_id,
        "version": rule.version,
        "source_citation_id": rule.source_citation_id,
        "rule_payload": rule.rule_payload,
    }
    if isinstance(rule, ScoreRule):
        for attribute in (
            "admission_year",
            "university_code",
            "university_name",
            "campus_code",
            "admission_round",
            "admission_track_code",
            "admission_track_name",
            "evidence_document_ref",
            "evidence_page",
            "evidence_location",
            "source_status",
        ):
            rule_snapshot[attribute] = getattr(rule, attribute)

    snapshot = {
        "contract_version": RULE_CONTRACT_SCHEMA_VERSION,
        "rule_type": rule_type,
        "rule": rule_snapshot,
        "track": None
        if track is None
        else {
            "id": track.id,
            "admission_round_id": track.admission_round_id,
            "program_id": track.program_id,
            "code": track.code,
            "name": track.name,
        },
        "admission_round": None
        if admission_round is None
        else {
            "id": admission_round.id,
            "institution_id": admission_round.institution_id,
            "academic_year": admission_round.academic_year,
            "code": admission_round.code,
            "name": admission_round.name,
        },
        "program": None
        if program is None
        else {
            "id": program.id,
            "campus_id": program.campus_id,
            "code": program.code,
            "name": program.name,
        },
        "campus": None
        if campus is None
        else {
            "id": campus.id,
            "code": campus.code,
            "institution_id": campus.institution_id,
            "name": campus.name,
        },
        "institution": None
        if institution is None
        else {
            "id": institution.id,
            "code": institution.code,
            "name": institution.name,
            "institution_type": institution.institution_type,
        },
        "citation": None
        if citation is None
        else {
            "id": citation.id,
            "source_document_id": citation.source_document_id,
            "source_document_page_id": citation.source_document_page_id,
            "page_number": citation.page_number,
            "locator": citation.locator,
            "excerpt_digest": citation.excerpt_digest,
        },
        "document": None
        if document is None
        else {
            "id": document.id,
            "academic_year": document.academic_year,
            "institution_id": document.institution_id,
            "campus_id": document.campus_id,
            "document_type": document.document_type,
            "document_status": document.document_status,
            "published_at": _canonical_datetime(document.published_at),
            "revision_label": document.revision_label,
            "supersedes_id": document.supersedes_id,
            "file_hash": document.file_hash,
            "page_count": document.page_count,
            "detected_years": document.detected_years,
            "year_consistency_status": document.year_consistency_status,
            "verification_status": document.verification_status,
        },
        "page": None
        if page is None
        else {
            "id": page.id,
            "source_document_id": page.source_document_id,
            "page_number": page.page_number,
            "detected_academic_year": page.detected_academic_year,
            "verification_status": page.verification_status,
        },
    }
    return _canonical_digest(snapshot)


def rule_contract_digest(session: Session, rule_type: str, rule: Any) -> str:
    return _contract_digest(session, rule_type, rule)


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
    audit_details = dict(details)
    if after_payload is not None:
        audit_details["contract_digest"] = _contract_digest(session, rule_type, rule)
        audit_details["contract_schema_version"] = RULE_CONTRACT_SCHEMA_VERSION
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
            details=audit_details,
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
    "GoldenTestRunEvidence",
    "HumanApproval",
    "PayloadChange",
    "RuleAdministrationError",
    "RuleExtractionEvidence",
    "RuleImpact",
    "RuleTestEvidence",
    "RuleVerificationEvidence",
    "RULE_CONTRACT_SCHEMA_VERSION",
    "clone_published_rule_as_draft",
    "compare_rule_impact",
    "compare_rule_payloads",
    "human_approve_tested_rule",
    "mark_rule_extracted",
    "mark_rule_tested",
    "publish_human_approved_rule",
    "record_golden_test_artifact",
    "record_rule_audit",
    "rule_contract_digest",
    "rule_payload_digest",
    "rule_model_for_type",
    "validate_rule_execution_contract",
    "validate_rule_publication_source",
    "verify_extracted_rule",
]
