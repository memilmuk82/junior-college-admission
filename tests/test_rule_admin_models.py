from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models import (
    AdmissionRound,
    AdmissionTrack,
    Campus,
    Institution,
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
from app.services.rule_admin import (
    RULE_CONTRACT_SCHEMA_VERSION,
    GoldenTestRunEvidence,
    HumanApproval,
    RuleAdministrationError,
    RuleExtractionEvidence,
    RuleTestEvidence,
    RuleVerificationEvidence,
    clone_published_rule_as_draft,
    compare_rule_impact,
    compare_rule_payloads,
    human_approve_tested_rule,
    mark_rule_extracted,
    mark_rule_tested,
    publish_human_approved_rule,
    record_golden_test_artifact,
    rule_contract_digest,
    rule_payload_digest,
    verify_extracted_rule,
)
from tests.test_consultations import _score_payload


@pytest.fixture
def session(postgres_engine: Engine) -> Iterator[Session]:
    connection = postgres_engine.connect()
    transaction = connection.begin()
    database_session = Session(bind=connection)
    try:
        yield database_session
    finally:
        database_session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _published_score_rule(session: Session) -> ScoreRule:
    institution = Institution(
        code="SYNTHETIC_U",
        name="합성 규칙 대학",
        institution_type="JUNIOR_COLLEGE",
    )
    session.add(institution)
    session.flush()
    campus = Campus(code="MAIN", institution_id=institution.id, name="합성 캠퍼스")
    session.add(campus)
    session.flush()
    program = Program(campus_id=campus.id, name="합성 학과")
    admission_round = AdmissionRound(
        institution_id=institution.id, academic_year=2027, code="EARLY_1", name="수시 1차"
    )
    session.add_all([program, admission_round])
    session.flush()
    track = AdmissionTrack(
        admission_round_id=admission_round.id,
        program_id=program.id,
        code="GENERAL",
        name="일반전형",
    )
    document = SourceDocument(
        academic_year=2027,
        institution_id=institution.id,
        campus_id=campus.id,
        document_type="FINAL_GUIDE",
        document_status="HUMAN_APPROVED",
        file_hash="d" * 64,
        page_count=1,
        detected_years=[2027],
        year_consistency_status="CONSISTENT",
        verification_status="HUMAN_APPROVED",
    )
    session.add_all([track, document])
    session.flush()
    page = SourceDocumentPage(
        source_document_id=document.id,
        page_number=1,
        detected_academic_year=2027,
        verification_status="HUMAN_APPROVED",
    )
    session.add(page)
    session.flush()
    citation = SourceCitation(
        source_document_id=document.id,
        source_document_page_id=page.id,
        page_number=1,
        locator="합성 표",
    )
    session.add(citation)
    session.flush()
    rule = ScoreRule(
        admission_track_id=track.id,
        version="official-v1",
        lifecycle_status="DRAFT",
        rule_payload=_score_payload(),
        source_citation_id=citation.id,
        independent_verified=False,
        admission_year=2027,
        university_code="SYNTHETIC_U",
        university_name="합성 규칙 대학",
        campus_code="MAIN",
        admission_round="EARLY_1",
        admission_track_code="GENERAL",
        admission_track_name="일반전형",
        evidence_document_ref=document.id,
        evidence_page=1,
        evidence_location="합성 표",
        source_status="FINAL_GUIDE",
        change_reason="합성 최초 규칙",
    )
    session.add(rule)
    session.flush()
    occurred_at = datetime(2026, 7, 12, tzinfo=UTC)
    _advance_to_tested(
        session,
        rule,
        occurred_at,
        golden_test_ref="tests/synthetic::v1",
    )
    human_approve_tested_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=rule.id,
        approval=HumanApproval("synthetic-admin", occurred_at, "HUMAN_APPROVED"),
    )
    publish_human_approved_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=rule.id,
        actor_ref="synthetic-admin",
        occurred_at=occurred_at,
    )
    return rule


def _independent_review(
    session: Session,
    rule: ScoreRule,
    reviewed_at: datetime,
    *,
    reviewer_ref: str = "synthetic-reviewer",
) -> RuleReview:
    review = RuleReview(
        rule_type="SCORE_RULE",
        rule_id=rule.id,
        review_kind="INDEPENDENT_VERIFICATION",
        review_status="APPROVED",
        reviewer_ref=reviewer_ref,
        reviewed_at=reviewed_at,
        payload_digest=rule_payload_digest(rule.rule_payload),
        contract_digest=rule_contract_digest(session, "SCORE_RULE", rule),
        contract_schema_version=RULE_CONTRACT_SCHEMA_VERSION,
        notes="합성 독립 검수",
    )
    session.add(review)
    session.flush()
    return review


def _advance_to_tested(
    session: Session,
    rule: ScoreRule,
    occurred_at: datetime,
    *,
    golden_test_ref: str,
    review: RuleReview | None = None,
) -> RuleReview:
    mark_rule_extracted(
        session,
        rule_type="SCORE_RULE",
        rule_id=rule.id,
        evidence=RuleExtractionEvidence("synthetic-admin", occurred_at, "EXTRACTED"),
    )
    selected_review = review or _independent_review(session, rule, occurred_at)
    verify_extracted_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=rule.id,
        evidence=RuleVerificationEvidence(
            "synthetic-admin",
            occurred_at,
            "VERIFIED",
            selected_review.id,
        ),
    )
    artifact = _record_golden_artifact(
        session,
        rule,
        selected_review,
        occurred_at,
        suite_ref=golden_test_ref,
    )
    mark_rule_tested(
        session,
        rule_type="SCORE_RULE",
        rule_id=rule.id,
        evidence=RuleTestEvidence(
            "synthetic-admin",
            occurred_at,
            "TESTED",
            artifact.artifact_ref,
            selected_review.id,
        ),
    )
    return selected_review


def _record_golden_artifact(
    session: Session,
    rule: ScoreRule,
    review: RuleReview,
    executed_at: datetime,
    *,
    suite_ref: str,
    failed_case_count: int = 0,
) -> RuleGoldenTestArtifact:
    case_count = 3
    return record_golden_test_artifact(
        session,
        rule_type="SCORE_RULE",
        rule_id=rule.id,
        evidence=GoldenTestRunEvidence(
            runner_ref="synthetic-pytest-runner",
            executed_at=executed_at,
            suite_ref=suite_ref,
            suite_digest="a" * 64,
            independent_review_id=review.id,
            case_count=case_count,
            passed_case_count=case_count - failed_case_count,
            failed_case_count=failed_case_count,
        ),
    )


def test_published_rule_is_cloned_approved_and_replaced_with_audit(session: Session) -> None:
    source = _published_score_rule(session)
    occurred_at = datetime(2026, 7, 13, 2, 0, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="official-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 변경 검수",
        occurred_at=occurred_at,
    )
    assert source.lifecycle_status == "PUBLISHED"
    assert draft.lifecycle_status == "DRAFT"
    assert draft.rule_payload == source.rule_payload
    assert draft.university_code == source.university_code
    assert draft.evidence_document_ref == source.evidence_document_ref
    assert draft.independent_verified is False
    assert draft.golden_test_rule_type is None
    lineage = session.scalar(
        select(RuleVersionLineage).where(RuleVersionLineage.rule_id == draft.id)
    )
    assert lineage is not None and lineage.supersedes_rule_id == source.id

    _advance_to_tested(
        session,
        draft,
        occurred_at,
        golden_test_ref="tests/synthetic::v2",
    )
    assert draft.golden_test_rule_type == "SCORE_RULE"
    approved = human_approve_tested_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        approval=HumanApproval("synthetic-admin", occurred_at, "HUMAN_APPROVED"),
    )
    publish_human_approved_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=approved.id,
        actor_ref="synthetic-admin",
        occurred_at=occurred_at,
    )
    assert approved.lifecycle_status == "PUBLISHED"
    assert source.lifecycle_status == "SUPERSEDED"
    actions = tuple(
        session.scalars(
            select(RuleAuditEvent.action).where(
                RuleAuditEvent.rule_type == "SCORE_RULE",
                RuleAuditEvent.rule_id == draft.id,
            )
        )
    )
    assert len(actions) == 6
    assert set(actions) == {
        "DRAFT_CLONED",
        "EXTRACTED",
        "VERIFIED",
        "TESTED",
        "HUMAN_APPROVED",
        "PUBLISHED",
    }
    assert (
        session.scalar(
            select(RuleAuditEvent.id).where(
                RuleAuditEvent.rule_type == "SCORE_RULE",
                RuleAuditEvent.rule_id == source.id,
                RuleAuditEvent.action == "SUPERSEDED",
            )
        )
        is not None
    )


def test_human_approval_requires_explicit_confirmation(session: Session) -> None:
    source = _published_score_rule(session)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="official-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 변경",
        occurred_at=datetime(2026, 7, 13, tzinfo=UTC),
    )
    _advance_to_tested(
        session,
        draft,
        datetime(2026, 7, 13, tzinfo=UTC),
        golden_test_ref="tests/synthetic::v2",
    )
    with pytest.raises(RuleAdministrationError):
        human_approve_tested_rule(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            approval=HumanApproval(
                "synthetic-admin", datetime(2026, 7, 13, tzinfo=UTC), "AI_APPROVED"
            ),
        )


def test_final_guide_replaces_implementation_plan_with_impact_and_lineage(
    session: Session,
) -> None:
    source = _published_score_rule(session)
    source_citation = session.get(SourceCitation, source.source_citation_id)
    assert source_citation is not None
    implementation_plan = session.get(SourceDocument, source_citation.source_document_id)
    assert implementation_plan is not None
    implementation_plan.document_type = "IMPLEMENTATION_PLAN"
    implementation_plan.revision_label = "synthetic-plan-v1"
    source.source_status = "IMPLEMENTATION_PLAN"
    source.rule_payload = _score_payload()
    implementation_transform = source.rule_payload["score_transform"]
    assert isinstance(implementation_transform, dict)
    implementation_transform["mode"] = "LINEAR"
    implementation_transform["base"] = "0"
    implementation_transform["multiplier"] = "1.00"

    occurred_at = datetime(2026, 7, 14, 5, 0, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="synthetic-final-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 최종 모집요강 교체",
        occurred_at=occurred_at,
    )
    final_payload = deepcopy(source.rule_payload)
    final_transform = final_payload["score_transform"]
    assert isinstance(final_transform, dict)
    final_transform["multiplier"] = "0.80"
    changes = compare_rule_payloads(source.rule_payload, final_payload)
    assert [(change.path, change.before, change.after) for change in changes] == [
        ("score_transform.multiplier", "1.00", "0.80")
    ]

    def evaluate(payload: dict[str, object], sample: dict[str, str]) -> Decimal:
        transform = payload["score_transform"]
        assert isinstance(transform, dict)
        return Decimal(sample["base_score"]) * Decimal(str(transform["multiplier"]))

    impacts = compare_rule_impact(
        source.rule_payload,
        final_payload,
        [{"sample_id": "synthetic-guide-replacement", "base_score": "80"}],
        evaluate,
    )
    assert (impacts[0].before, impacts[0].after, impacts[0].delta) == (
        Decimal("80.00"),
        Decimal("64.00"),
        Decimal("-16.00"),
    )

    final_guide = SourceDocument(
        academic_year=2027,
        institution_id=implementation_plan.institution_id,
        campus_id=implementation_plan.campus_id,
        document_type="FINAL_GUIDE",
        document_status="HUMAN_APPROVED",
        revision_label="synthetic-final-v2",
        supersedes_id=implementation_plan.id,
        file_hash="e" * 64,
        page_count=2,
        detected_years=[2027],
        year_consistency_status="CONSISTENT",
        verification_status="HUMAN_APPROVED",
    )
    session.add(final_guide)
    session.flush()
    final_page = SourceDocumentPage(
        source_document_id=final_guide.id,
        page_number=2,
        detected_academic_year=2027,
        verification_status="HUMAN_APPROVED",
    )
    session.add(final_page)
    session.flush()
    final_citation = SourceCitation(
        source_document_id=final_guide.id,
        source_document_page_id=final_page.id,
        page_number=2,
        locator="합성 최종 산식 표",
    )
    session.add(final_citation)
    session.flush()

    draft.rule_payload = final_payload
    draft.source_citation_id = final_citation.id
    draft.evidence_document_ref = final_guide.id
    draft.evidence_page = 2
    draft.evidence_location = "합성 최종 산식 표"
    draft.source_status = "FINAL_GUIDE"
    _advance_to_tested(
        session,
        draft,
        occurred_at,
        golden_test_ref="tests/synthetic::final-guide-v2",
    )
    human_approve_tested_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        approval=HumanApproval("synthetic-admin", occurred_at, "HUMAN_APPROVED"),
    )
    publish_human_approved_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        actor_ref="synthetic-admin",
        occurred_at=occurred_at,
    )

    active = session.scalar(
        select(ScoreRule).where(
            ScoreRule.admission_track_id == source.admission_track_id,
            ScoreRule.lifecycle_status == "PUBLISHED",
        )
    )
    assert active is not None and active.id == draft.id
    assert source.lifecycle_status == "SUPERSEDED"
    source_transform = source.rule_payload["score_transform"]
    assert isinstance(source_transform, dict)
    assert source_transform["multiplier"] == "1.00"
    assert final_guide.supersedes_id == implementation_plan.id
    assert implementation_plan.document_type == "IMPLEMENTATION_PLAN"


def test_tested_transition_requires_distinct_approved_review_and_safe_golden_ref(
    session: Session,
) -> None:
    source = _published_score_rule(session)
    occurred_at = datetime(2026, 7, 15, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="synthetic-review-gate-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 독립 검수 게이트",
        occurred_at=occurred_at,
    )
    self_review = _independent_review(
        session,
        draft,
        occurred_at,
        reviewer_ref="synthetic-admin",
    )
    mark_rule_extracted(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleExtractionEvidence("synthetic-admin", occurred_at, "EXTRACTED"),
    )

    with pytest.raises(RuleAdministrationError, match="별도 검수자"):
        verify_extracted_rule(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            evidence=RuleVerificationEvidence(
                "synthetic-admin",
                occurred_at,
                "VERIFIED",
                self_review.id,
            ),
        )

    independent_review = _independent_review(
        session,
        draft,
        occurred_at,
        reviewer_ref="synthetic-second-reviewer",
    )
    verify_extracted_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleVerificationEvidence(
            "synthetic-admin",
            occurred_at,
            "VERIFIED",
            independent_review.id,
        ),
    )
    with pytest.raises(RuleAdministrationError, match="골든 테스트"):
        mark_rule_tested(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            evidence=RuleTestEvidence(
                "synthetic-admin",
                occurred_at,
                "TESTED",
                "../unsafe",
                independent_review.id,
            ),
        )


def test_tested_transition_requires_recorded_passed_golden_artifact(session: Session) -> None:
    source = _published_score_rule(session)
    occurred_at = datetime(2026, 7, 15, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="synthetic-golden-gate-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 골든 artifact 게이트",
        occurred_at=occurred_at,
    )
    mark_rule_extracted(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleExtractionEvidence("synthetic-admin", occurred_at, "EXTRACTED"),
    )
    review = _independent_review(session, draft, occurred_at)
    verify_extracted_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleVerificationEvidence(
            "synthetic-admin",
            occurred_at,
            "VERIFIED",
            review.id,
        ),
    )

    with pytest.raises(RuleAdministrationError, match="PASSED 골든 테스트 artifact"):
        mark_rule_tested(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            evidence=RuleTestEvidence(
                "synthetic-admin",
                occurred_at,
                "TESTED",
                "golden-run/not-recorded",
                review.id,
            ),
        )

    failed_artifact = _record_golden_artifact(
        session,
        draft,
        review,
        occurred_at,
        suite_ref="tests/synthetic::failed-suite",
        failed_case_count=1,
    )
    assert failed_artifact.result_status == "FAILED"
    assert failed_artifact.passed_case_count == 2
    assert failed_artifact.failed_case_count == 1
    with pytest.raises(RuleAdministrationError, match="PASSED 골든 테스트 artifact"):
        mark_rule_tested(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            evidence=RuleTestEvidence(
                "synthetic-admin",
                occurred_at,
                "TESTED",
                failed_artifact.artifact_ref,
                review.id,
            ),
        )

    passed_artifact = _record_golden_artifact(
        session,
        draft,
        review,
        occurred_at,
        suite_ref="tests/synthetic::passed-suite",
    )
    tested = mark_rule_tested(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleTestEvidence(
            "synthetic-admin",
            occurred_at,
            "TESTED",
            passed_artifact.artifact_ref,
            review.id,
        ),
    )

    assert tested.lifecycle_status == "TESTED"
    assert passed_artifact.result_status == "PASSED"
    assert passed_artifact.passed_case_count == passed_artifact.case_count == 3
    assert passed_artifact.failed_case_count == 0
    tested_event = session.scalar(
        select(RuleAuditEvent).where(
            RuleAuditEvent.rule_type == "SCORE_RULE",
            RuleAuditEvent.rule_id == draft.id,
            RuleAuditEvent.action == "TESTED",
        )
    )
    assert tested_event is not None
    assert tested_event.details["golden_artifact_id"] == passed_artifact.id
    assert tested_event.details["golden_artifact_digest"] == passed_artifact.artifact_digest
    assert tested_event.details["golden_artifact_case_count"] == 3


def test_tested_transition_rejects_artifact_recorded_for_another_rule(
    session: Session,
) -> None:
    source = _published_score_rule(session)
    occurred_at = datetime(2026, 7, 15, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="synthetic-artifact-owner-a-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 artifact 규칙 결속 A",
        occurred_at=occurred_at,
    )
    other_draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="synthetic-artifact-owner-b-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 artifact 규칙 결속 B",
        occurred_at=occurred_at,
    )
    reviews: list[RuleReview] = []
    for candidate, reviewer_ref in (
        (draft, "synthetic-reviewer-a"),
        (other_draft, "synthetic-reviewer-b"),
    ):
        mark_rule_extracted(
            session,
            rule_type="SCORE_RULE",
            rule_id=candidate.id,
            evidence=RuleExtractionEvidence("synthetic-admin", occurred_at, "EXTRACTED"),
        )
        review = _independent_review(
            session,
            candidate,
            occurred_at,
            reviewer_ref=reviewer_ref,
        )
        verify_extracted_rule(
            session,
            rule_type="SCORE_RULE",
            rule_id=candidate.id,
            evidence=RuleVerificationEvidence(
                "synthetic-admin",
                occurred_at,
                "VERIFIED",
                review.id,
            ),
        )
        reviews.append(review)

    other_artifact = _record_golden_artifact(
        session,
        other_draft,
        reviews[1],
        occurred_at,
        suite_ref="tests/synthetic::other-rule-suite",
    )
    with pytest.raises(RuleAdministrationError, match="PASSED 골든 테스트 artifact"):
        mark_rule_tested(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            evidence=RuleTestEvidence(
                "synthetic-admin",
                occurred_at,
                "TESTED",
                other_artifact.artifact_ref,
                reviews[0].id,
            ),
        )


def test_golden_artifact_mutation_blocks_human_approval(session: Session) -> None:
    source = _published_score_rule(session)
    occurred_at = datetime(2026, 7, 15, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="synthetic-artifact-tamper-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 artifact 변조 검증",
        occurred_at=occurred_at,
    )
    _advance_to_tested(
        session,
        draft,
        occurred_at,
        golden_test_ref="tests/synthetic::tamper-suite",
    )
    artifact = session.scalar(
        select(RuleGoldenTestArtifact).where(
            RuleGoldenTestArtifact.artifact_ref == draft.golden_test_ref
        )
    )
    assert artifact is not None
    artifact.artifact_digest = "f" * 64
    session.flush()

    with pytest.raises(RuleAdministrationError, match="PASSED 골든 테스트 artifact"):
        human_approve_tested_rule(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            approval=HumanApproval("synthetic-admin", occurred_at, "HUMAN_APPROVED"),
        )


def test_source_year_mismatch_blocks_tested_transition(session: Session) -> None:
    source = _published_score_rule(session)
    occurred_at = datetime(2026, 7, 15, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="synthetic-year-gate-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 연도 검증",
        occurred_at=occurred_at,
    )
    citation = session.get(SourceCitation, draft.source_citation_id)
    assert citation is not None
    document = session.get(SourceDocument, citation.source_document_id)
    assert document is not None
    document.academic_year = 2026
    document.detected_years = [2026]
    review = _independent_review(session, draft, occurred_at)
    mark_rule_extracted(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleExtractionEvidence("synthetic-admin", occurred_at, "EXTRACTED"),
    )

    with pytest.raises(RuleAdministrationError, match="모집학년도"):
        verify_extracted_rule(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            evidence=RuleVerificationEvidence(
                "synthetic-admin",
                occurred_at,
                "VERIFIED",
                review.id,
            ),
        )


@pytest.mark.parametrize(
    ("attribute", "mismatched_code", "message"),
    (
        ("university_code", "OTHER_UNIVERSITY", "대학 코드"),
        ("campus_code", "OTHER_CAMPUS", "캠퍼스 코드"),
    ),
)
def test_verified_transition_requires_canonical_institution_and_campus_codes(
    session: Session,
    attribute: str,
    mismatched_code: str,
    message: str,
) -> None:
    source = _published_score_rule(session)
    occurred_at = datetime(2026, 7, 15, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version=f"synthetic-canonical-{attribute}-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 canonical 코드 결속 검증",
        occurred_at=occurred_at,
    )
    setattr(draft, attribute, mismatched_code)
    review = _independent_review(session, draft, occurred_at)
    mark_rule_extracted(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleExtractionEvidence("synthetic-admin", occurred_at, "EXTRACTED"),
    )

    with pytest.raises(RuleAdministrationError, match=message):
        verify_extracted_rule(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            evidence=RuleVerificationEvidence(
                "synthetic-admin",
                occurred_at,
                "VERIFIED",
                review.id,
            ),
        )


def test_document_state_is_rechecked_before_human_approval_and_publish(
    session: Session,
) -> None:
    source = _published_score_rule(session)
    occurred_at = datetime(2026, 7, 15, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="synthetic-state-gate-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 문서 상태 재검증",
        occurred_at=occurred_at,
    )
    _advance_to_tested(
        session,
        draft,
        occurred_at,
        golden_test_ref="tests/synthetic::state-gate",
    )
    citation = session.get(SourceCitation, draft.source_citation_id)
    assert citation is not None
    document = session.get(SourceDocument, citation.source_document_id)
    assert document is not None
    document.document_status = "SUPERSEDED"

    with pytest.raises(RuleAdministrationError, match="사람 검수된"):
        human_approve_tested_rule(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            approval=HumanApproval("synthetic-admin", occurred_at, "HUMAN_APPROVED"),
        )

    document.document_status = "HUMAN_APPROVED"
    human_approve_tested_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        approval=HumanApproval("synthetic-admin", occurred_at, "HUMAN_APPROVED"),
    )
    document.document_status = "SUPERSEDED"
    with pytest.raises(RuleAdministrationError, match="사람 검수된"):
        publish_human_approved_rule(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            actor_ref="synthetic-admin",
            occurred_at=occurred_at,
        )


def test_lifecycle_cannot_skip_extracted_and_verified(session: Session) -> None:
    source = _published_score_rule(session)
    occurred_at = datetime(2026, 7, 15, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="synthetic-no-skip-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 생명주기 순서 검증",
        occurred_at=occurred_at,
    )
    review = _independent_review(session, draft, occurred_at)

    with pytest.raises(RuleAdministrationError, match="VERIFIED 규칙만"):
        mark_rule_tested(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            evidence=RuleTestEvidence(
                "synthetic-admin",
                occurred_at,
                "TESTED",
                "tests/synthetic::no-skip",
                review.id,
            ),
        )


def test_verified_payload_digest_and_review_are_rechecked(session: Session) -> None:
    source = _published_score_rule(session)
    occurred_at = datetime(2026, 7, 15, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="synthetic-digest-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 payload 결속 검증",
        occurred_at=occurred_at,
    )
    review = _independent_review(session, draft, occurred_at)
    mark_rule_extracted(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleExtractionEvidence("synthetic-admin", occurred_at, "EXTRACTED"),
    )
    verify_extracted_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleVerificationEvidence("synthetic-admin", occurred_at, "VERIFIED", review.id),
    )
    draft.rule_payload["maximum_score"] = "8"

    with pytest.raises(RuleAdministrationError, match="현재 payload"):
        mark_rule_tested(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            evidence=RuleTestEvidence(
                "synthetic-admin",
                occurred_at,
                "TESTED",
                "tests/synthetic::digest",
                review.id,
            ),
        )

    draft.rule_payload["maximum_score"] = source.rule_payload["maximum_score"]
    artifact = _record_golden_artifact(
        session,
        draft,
        review,
        occurred_at,
        suite_ref="tests/synthetic::digest",
    )
    mark_rule_tested(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleTestEvidence(
            "synthetic-admin",
            occurred_at,
            "TESTED",
            artifact.artifact_ref,
            review.id,
        ),
    )
    review.review_status = "REJECTED"
    with pytest.raises(RuleAdministrationError, match="취소·변경"):
        human_approve_tested_rule(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            approval=HumanApproval("synthetic-admin", occurred_at, "HUMAN_APPROVED"),
        )


def test_tested_transition_reuses_verified_review(session: Session) -> None:
    source = _published_score_rule(session)
    occurred_at = datetime(2026, 7, 15, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="synthetic-same-review-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 동일 검수 결속 검증",
        occurred_at=occurred_at,
    )
    verified_review = _independent_review(session, draft, occurred_at)
    other_review = _independent_review(
        session,
        draft,
        occurred_at,
        reviewer_ref="synthetic-third-reviewer",
    )
    mark_rule_extracted(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleExtractionEvidence("synthetic-admin", occurred_at, "EXTRACTED"),
    )
    verify_extracted_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleVerificationEvidence(
            "synthetic-admin", occurred_at, "VERIFIED", verified_review.id
        ),
    )

    with pytest.raises(RuleAdministrationError, match="같은 독립 검수"):
        mark_rule_tested(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            evidence=RuleTestEvidence(
                "synthetic-admin",
                occurred_at,
                "TESTED",
                "tests/synthetic::same-review",
                other_review.id,
            ),
        )


def test_verified_contract_digest_blocks_evidence_rebinding(session: Session) -> None:
    source = _published_score_rule(session)
    occurred_at = datetime(2026, 7, 15, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="synthetic-contract-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 규칙 근거 결속 검증",
        occurred_at=occurred_at,
    )
    review = _independent_review(session, draft, occurred_at)
    mark_rule_extracted(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleExtractionEvidence("synthetic-admin", occurred_at, "EXTRACTED"),
    )
    verify_extracted_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleVerificationEvidence("synthetic-admin", occurred_at, "VERIFIED", review.id),
    )
    citation = session.get(SourceCitation, draft.source_citation_id)
    assert citation is not None
    citation.locator = "변경된 합성 표"
    draft.evidence_location = "변경된 합성 표"

    with pytest.raises(RuleAdministrationError, match="규칙·근거"):
        mark_rule_tested(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            evidence=RuleTestEvidence(
                "synthetic-admin",
                occurred_at,
                "TESTED",
                "tests/synthetic::contract",
                review.id,
            ),
        )


def test_contract_digest_normalizes_document_timestamp_timezone(session: Session) -> None:
    rule = _published_score_rule(session)
    citation = session.get(SourceCitation, rule.source_citation_id)
    assert citation is not None
    document = session.get(SourceDocument, citation.source_document_id)
    assert document is not None
    document.published_at = datetime(
        2026,
        7,
        15,
        9,
        30,
        tzinfo=timezone(timedelta(hours=9)),
    )
    session.flush()
    digest_before_reload = rule_contract_digest(session, "SCORE_RULE", rule)

    session.expire(document, ["published_at"])
    assert document.published_at is not None
    digest_after_reload = rule_contract_digest(session, "SCORE_RULE", rule)

    assert digest_after_reload == digest_before_reload


def test_verified_transition_requires_human_approved_page_record(session: Session) -> None:
    source = _published_score_rule(session)
    occurred_at = datetime(2026, 7, 15, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="synthetic-page-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 페이지 검수 검증",
        occurred_at=occurred_at,
    )
    citation = session.get(SourceCitation, draft.source_citation_id)
    assert citation is not None
    citation.source_document_page_id = None
    review = _independent_review(session, draft, occurred_at)
    mark_rule_extracted(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        evidence=RuleExtractionEvidence("synthetic-admin", occurred_at, "EXTRACTED"),
    )

    with pytest.raises(RuleAdministrationError, match="페이지 기록"):
        verify_extracted_rule(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            evidence=RuleVerificationEvidence(
                "synthetic-admin", occurred_at, "VERIFIED", review.id
            ),
        )
