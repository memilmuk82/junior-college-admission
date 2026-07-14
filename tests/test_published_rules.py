from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
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
    ScoreRule,
    SourceCitation,
    SourceDocument,
    SourceDocumentPage,
    StudentAcademicRecord,
    StudentCourseRecord,
)
from app.services.application_policies import (
    ApplicationChoice,
    ApplicationHistory,
    DisqualificationStatus,
    MultipleApplicationStatus,
    SensitiveDisqualificationFacts,
    evaluate_published_disqualification,
    evaluate_published_multiple_application,
)
from app.services.eligibility import (
    EligibilityDecision,
    EligibilityStatus,
    EligibilityTrace,
    StudentFacts,
)
from app.services.published_rules import (
    PublishedRuleError,
    PublishedRuleNotFound,
    evaluate_published_eligibility,
    load_published_multiple_application_rule,
    load_published_score_rule,
)
from app.services.rule_admin import (
    RULE_CONTRACT_SCHEMA_VERSION,
    GoldenTestRunEvidence,
    HumanApproval,
    RuleAdministrationError,
    RuleExtractionEvidence,
    RuleTestEvidence,
    RuleVerificationEvidence,
    human_approve_tested_rule,
    mark_rule_extracted,
    mark_rule_tested,
    publish_human_approved_rule,
    record_golden_test_artifact,
    rule_contract_digest,
    rule_payload_digest,
    verify_extracted_rule,
)
from app.services.score_inputs import ScoreInputStatus, evaluate_published_score_inputs
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


def _track_and_citation(session: Session) -> tuple[AdmissionTrack, SourceCitation]:
    institution = Institution(
        code="SYNTHETIC_U",
        name="합성 규칙 전문대",
        institution_type="JUNIOR_COLLEGE",
    )
    session.add(institution)
    session.flush()
    campus = Campus(
        code="SYNTHETIC_MAIN",
        institution_id=institution.id,
        name="합성 캠퍼스",
    )
    session.add(campus)
    session.flush()
    program = Program(campus_id=campus.id, name="합성 학과")
    admission_round = AdmissionRound(
        institution_id=institution.id,
        academic_year=2027,
        code="SYNTHETIC_ROUND",
        name="합성 모집시기",
    )
    session.add_all([program, admission_round])
    session.flush()
    track = AdmissionTrack(
        admission_round_id=admission_round.id,
        program_id=program.id,
        code="SYNTHETIC_TRACK",
        name="합성 전형",
    )
    document = SourceDocument(
        academic_year=2027,
        institution_id=institution.id,
        campus_id=campus.id,
        document_type="FINAL_GUIDE",
        document_status="PUBLISHED",
        published_at=datetime(2026, 7, 12, tzinfo=UTC),
        file_hash="f" * 64,
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
        excerpt_digest="e" * 64,
    )
    session.add(citation)
    session.flush()
    return track, citation


def _metadata(track: AdmissionTrack, citation: SourceCitation) -> dict[str, object]:
    return {
        "admission_track_id": track.id,
        "lifecycle_status": "PUBLISHED",
        "source_citation_id": citation.id,
        "independent_verified": True,
        "golden_test_ref": "tests/test_published_rules.py",
        "human_approved_at": datetime(2026, 7, 12, tzinfo=UTC),
    }


def _score_metadata(track: AdmissionTrack, citation: SourceCitation) -> dict[str, object]:
    return _metadata(track, citation) | {
        "admission_year": 2027,
        "university_code": "SYNTHETIC_U",
        "university_name": "합성 규칙 전문대",
        "campus_code": "SYNTHETIC_MAIN",
        "admission_round": "SYNTHETIC_ROUND",
        "admission_track_code": "SYNTHETIC_TRACK",
        "admission_track_name": "합성 전형",
        "evidence_document_ref": citation.source_document_id,
        "evidence_page": citation.page_number,
        "evidence_location": citation.locator,
        "source_status": "FINAL_GUIDE",
    }


def _eligibility_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "cases": [
            {
                "case_id": "synthetic_general",
                "when": {
                    "fact": "final_school_type",
                    "op": "eq",
                    "value": "GENERAL",
                },
                "status": "ELIGIBLE",
                "reason_code": "SYNTHETIC_GENERAL",
            }
        ],
        "default": {"status": "INELIGIBLE", "reason_code": "SYNTHETIC_DEFAULT"},
    }


def _persist_published_rule(
    session: Session,
    rule: AdmissionEligibilityRule
    | MultipleApplicationRule
    | DisqualificationRule
    | GradeSourceScopeRule
    | ScoreRule,
) -> None:
    occurred_at = datetime(2026, 7, 12, tzinfo=UTC)
    suite_ref = rule.golden_test_ref or "tests/synthetic::published-rule-suite"
    rule.lifecycle_status = "DRAFT"
    rule.independent_verified = False
    rule.golden_test_ref = None
    rule.human_approved_at = None
    session.add(rule)
    session.flush()
    rule_type = {
        AdmissionEligibilityRule: "ADMISSION_ELIGIBILITY_RULE",
        MultipleApplicationRule: "MULTIPLE_APPLICATION_RULE",
        DisqualificationRule: "DISQUALIFICATION_RULE",
        GradeSourceScopeRule: "GRADE_SOURCE_SCOPE_RULE",
        ScoreRule: "SCORE_RULE",
    }[type(rule)]
    mark_rule_extracted(
        session,
        rule_type=rule_type,
        rule_id=rule.id,
        evidence=RuleExtractionEvidence("synthetic-admin", occurred_at, "EXTRACTED"),
    )
    review = RuleReview(
        rule_type=rule_type,
        rule_id=rule.id,
        review_kind="INDEPENDENT_VERIFICATION",
        review_status="APPROVED",
        reviewer_ref="synthetic-independent-reviewer",
        reviewed_at=occurred_at,
        payload_digest=rule_payload_digest(rule.rule_payload),
        contract_digest=rule_contract_digest(session, rule_type, rule),
        contract_schema_version=RULE_CONTRACT_SCHEMA_VERSION,
    )
    session.add(review)
    session.flush()
    verify_extracted_rule(
        session,
        rule_type=rule_type,
        rule_id=rule.id,
        evidence=RuleVerificationEvidence(
            "synthetic-admin",
            occurred_at,
            "VERIFIED",
            review.id,
        ),
    )
    artifact = record_golden_test_artifact(
        session,
        rule_type=rule_type,
        rule_id=rule.id,
        evidence=GoldenTestRunEvidence(
            runner_ref="synthetic-pytest-runner",
            executed_at=occurred_at,
            suite_ref=suite_ref,
            suite_digest="b" * 64,
            independent_review_id=review.id,
            case_count=2,
            passed_case_count=2,
            failed_case_count=0,
        ),
    )
    mark_rule_tested(
        session,
        rule_type=rule_type,
        rule_id=rule.id,
        evidence=RuleTestEvidence(
            "synthetic-admin",
            occurred_at,
            "TESTED",
            artifact.artifact_ref,
            review.id,
        ),
    )
    human_approve_tested_rule(
        session,
        rule_type=rule_type,
        rule_id=rule.id,
        approval=HumanApproval("synthetic-admin", occurred_at, "HUMAN_APPROVED"),
    )
    publish_human_approved_rule(
        session,
        rule_type=rule_type,
        rule_id=rule.id,
        actor_ref="synthetic-admin",
        occurred_at=occurred_at,
    )


def test_published_eligibility_rule_is_loaded_and_draft_is_ignored(
    session: Session,
) -> None:
    track, citation = _track_and_citation(session)
    _persist_published_rule(
        session,
        AdmissionEligibilityRule(
            version="synthetic-published-v1",
            rule_payload=_eligibility_payload(),
            **_metadata(track, citation),
        ),
    )
    session.add(
        AdmissionEligibilityRule(
            admission_track_id=track.id,
            version="synthetic-draft-v2",
            lifecycle_status="DRAFT",
            rule_payload={"invalid_draft_is_not_loaded": True},
            independent_verified=False,
        )
    )
    session.flush()

    decision = evaluate_published_eligibility(
        session, track.id, StudentFacts(final_school_type="GENERAL")
    )

    assert decision.status is EligibilityStatus.ELIGIBLE
    assert decision.trace.rule_version == "synthetic-published-v1"


def test_missing_published_rule_is_explicit(session: Session) -> None:
    track, _citation = _track_and_citation(session)

    with pytest.raises(PublishedRuleNotFound):
        evaluate_published_eligibility(session, track.id, StudentFacts())


def test_invalid_published_eligibility_payload_is_explicit(session: Session) -> None:
    track, citation = _track_and_citation(session)
    rule = AdmissionEligibilityRule(
        version="synthetic-invalid-v1",
        rule_payload=_eligibility_payload(),
        **_metadata(track, citation),
    )
    _persist_published_rule(session, rule)
    rule.rule_payload = {"expression": "not executable"}
    session.flush()

    with pytest.raises(PublishedRuleError):
        evaluate_published_eligibility(session, track.id, StudentFacts())


@pytest.mark.parametrize(
    "model",
    [
        AdmissionEligibilityRule,
        MultipleApplicationRule,
        DisqualificationRule,
        GradeSourceScopeRule,
        ScoreRule,
    ],
)
def test_database_rejects_two_published_versions_per_track(
    session: Session,
    model: type[
        AdmissionEligibilityRule
        | MultipleApplicationRule
        | DisqualificationRule
        | GradeSourceScopeRule
        | ScoreRule
    ],
) -> None:
    track, citation = _track_and_citation(session)
    session.add_all(
        [
            model(version="synthetic-v1", rule_payload={}, **_metadata(track, citation)),
            model(version="synthetic-v2", rule_payload={}, **_metadata(track, citation)),
        ]
    )

    with pytest.raises(IntegrityError):
        session.flush()


def test_score_rule_has_separate_versioned_loader(session: Session) -> None:
    track, citation = _track_and_citation(session)
    _persist_published_rule(
        session,
        ScoreRule(
            version="synthetic-score-v1",
            rule_payload=_score_payload(),
            **_score_metadata(track, citation),
        ),
    )

    rule = load_published_score_rule(session, track.id)

    assert rule.version == "synthetic-score-v1"
    assert rule.rule_id


@pytest.mark.parametrize("node_name", ("institution", "campus"))
def test_published_score_rule_fails_closed_when_canonical_code_changes(
    session: Session,
    node_name: str,
) -> None:
    track, citation = _track_and_citation(session)
    stored = ScoreRule(
        version=f"synthetic-canonical-{node_name}-v1",
        rule_payload=_score_payload(),
        **_score_metadata(track, citation),
    )
    _persist_published_rule(session, stored)
    admission_round = session.get(AdmissionRound, track.admission_round_id)
    program = session.get(Program, track.program_id)
    assert admission_round is not None and program is not None
    institution = session.get(Institution, admission_round.institution_id)
    campus = session.get(Campus, program.campus_id)
    assert institution is not None and campus is not None
    if node_name == "institution":
        institution.code = "CHANGED_UNIVERSITY"
    else:
        campus.code = "CHANGED_CAMPUS"
    session.flush()

    with pytest.raises(PublishedRuleError, match="무결성 검증") as error_info:
        load_published_score_rule(session, track.id)
    assert isinstance(error_info.value.__cause__, RuleAdministrationError)
    assert "코드" in str(error_info.value.__cause__)


def test_published_loader_rejects_tampered_artifact_and_database_restricts_deletion(
    session: Session,
) -> None:
    track, citation = _track_and_citation(session)
    stored = ScoreRule(
        version="synthetic-artifact-recheck-v1",
        rule_payload=_score_payload(),
        **_score_metadata(track, citation),
    )
    _persist_published_rule(session, stored)
    artifact = session.scalar(
        select(RuleGoldenTestArtifact).where(
            RuleGoldenTestArtifact.artifact_ref == stored.golden_test_ref
        )
    )
    assert artifact is not None
    original_digest = artifact.artifact_digest
    artifact.artifact_digest = "c" * 64
    session.flush()

    with pytest.raises(PublishedRuleError, match="무결성 검증") as error_info:
        load_published_score_rule(session, track.id)
    assert isinstance(error_info.value.__cause__, RuleAdministrationError)
    assert "PASSED 골든 테스트 artifact" in str(error_info.value.__cause__)

    artifact.artifact_digest = original_digest
    session.flush()
    with pytest.raises(IntegrityError):
        with session.begin_nested():
            session.delete(artifact)
            session.flush()

    session.expire_all()
    assert session.get(RuleGoldenTestArtifact, artifact.id) is not None
    assert load_published_score_rule(session, track.id).rule_id == stored.id


def test_published_loader_rechecks_source_document_status(session: Session) -> None:
    track, citation = _track_and_citation(session)
    _persist_published_rule(
        session,
        ScoreRule(
            version="synthetic-source-recheck-v1",
            rule_payload=_score_payload(),
            **_score_metadata(track, citation),
        ),
    )
    document = session.get(SourceDocument, citation.source_document_id)
    assert document is not None
    document.document_status = "SUPERSEDED"

    with pytest.raises(PublishedRuleError, match="무결성 검증"):
        load_published_score_rule(session, track.id)


def test_published_loader_requires_complete_audit_lifecycle(session: Session) -> None:
    track, citation = _track_and_citation(session)
    rule = ScoreRule(
        version="synthetic-audit-chain-v1",
        rule_payload=_score_payload(),
        **_score_metadata(track, citation),
    )
    _persist_published_rule(session, rule)
    extracted = session.scalar(
        select(RuleAuditEvent).where(
            RuleAuditEvent.rule_type == "SCORE_RULE",
            RuleAuditEvent.rule_id == rule.id,
            RuleAuditEvent.action == "EXTRACTED",
        )
    )
    assert extracted is not None
    session.delete(extracted)
    session.flush()

    with pytest.raises(PublishedRuleError, match="무결성 검증") as error_info:
        load_published_score_rule(session, track.id)
    assert isinstance(error_info.value.__cause__, RuleAdministrationError)
    assert "EXTRACTED" in str(error_info.value.__cause__)


def test_published_loader_rejects_reversed_audit_timestamps(session: Session) -> None:
    track, citation = _track_and_citation(session)
    rule = ScoreRule(
        version="synthetic-audit-time-v1",
        rule_payload=_score_payload(),
        **_score_metadata(track, citation),
    )
    _persist_published_rule(session, rule)
    events = {
        event.action: event
        for event in session.scalars(
            select(RuleAuditEvent).where(
                RuleAuditEvent.rule_type == "SCORE_RULE",
                RuleAuditEvent.rule_id == rule.id,
            )
        )
    }
    assert {"EXTRACTED", "VERIFIED", "HUMAN_APPROVED", "PUBLISHED"} <= events.keys()
    events["EXTRACTED"].occurred_at = datetime(2026, 7, 13, tzinfo=UTC)
    rule.human_approved_at = datetime(2026, 7, 14, tzinfo=UTC)
    events["HUMAN_APPROVED"].occurred_at = rule.human_approved_at
    events["PUBLISHED"].occurred_at = rule.human_approved_at
    session.flush()

    with pytest.raises(PublishedRuleError, match="무결성 검증") as error_info:
        load_published_score_rule(session, track.id)
    assert isinstance(error_info.value.__cause__, RuleAdministrationError)
    assert "시각 순서" in str(error_info.value.__cause__)


def test_multiple_application_rule_has_separate_loader(session: Session) -> None:
    track, citation = _track_and_citation(session)
    _persist_published_rule(
        session,
        MultipleApplicationRule(
            version="synthetic-multiple-v1",
            rule_payload={
                "schema_version": 1,
                "limits": {"total": 2, "per_campus": 1},
                "forbidden_track_combinations": [],
                "reason_codes": {
                    "allowed": "SYNTHETIC_ALLOWED",
                    "history_incomplete": "SYNTHETIC_HISTORY_INCOMPLETE",
                    "max_applications": "SYNTHETIC_MAX_APPLICATIONS",
                    "max_per_campus": "SYNTHETIC_MAX_PER_CAMPUS",
                    "forbidden_combination": "SYNTHETIC_FORBIDDEN",
                },
            },
            **_metadata(track, citation),
        ),
    )

    rule = load_published_multiple_application_rule(session, track.id)
    decision = evaluate_published_multiple_application(
        session,
        track.id,
        candidate=ApplicationChoice(
            track_id=track.id,
            institution_id="synthetic-institution",
            campus_id="synthetic-campus",
        ),
        history=ApplicationHistory(choices=(), is_complete=True),
    )

    assert rule.version == "synthetic-multiple-v1"
    assert rule.payload["schema_version"] == 1
    assert decision.status is MultipleApplicationStatus.ALLOWED


def test_sensitive_disqualification_value_is_not_persisted(session: Session) -> None:
    track, citation = _track_and_citation(session)
    stored_payload = {
        "schema_version": 1,
        "cases": [
            {
                "case_id": "synthetic_sensitive",
                "when": {"fact": "additional.sensitive_flag", "op": "is_true"},
                "status": "INELIGIBLE",
                "reason_code": "SYNTHETIC_DISQUALIFIED",
            }
        ],
        "default": {"status": "ELIGIBLE", "reason_code": "SYNTHETIC_CLEAR"},
    }
    rule = DisqualificationRule(
        version="synthetic-disqualification-v1",
        rule_payload=stored_payload,
        **_metadata(track, citation),
    )
    _persist_published_rule(session, rule)

    decision = evaluate_published_disqualification(
        session,
        track.id,
        SensitiveDisqualificationFacts({"sensitive_flag": True}),
    )
    session.expire_all()
    persisted_payload = session.scalar(
        select(DisqualificationRule.rule_payload).where(DisqualificationRule.id == rule.id)
    )

    assert decision.status is DisqualificationStatus.DISQUALIFIED
    assert persisted_payload == stored_payload
    assert "actual_value" not in repr(decision.trace)


def test_published_grade_scope_selects_verified_database_records(
    session: Session,
) -> None:
    track, citation = _track_and_citation(session)
    _persist_published_rule(
        session,
        GradeSourceScopeRule(
            version="synthetic-scope-v1",
            rule_payload={"schema_version": 1, "policy": "HOME_ONLY"},
            **_metadata(track, citation),
        ),
    )
    home_record = StudentAcademicRecord(
        student_id="synthetic-score-student",
        academic_year=2026,
        grade=2,
        semester=2,
        record_source="HOME_SCHOOL_RECORD",
        verification_status="USER_VERIFIED",
    )
    vocational_record = StudentAcademicRecord(
        student_id="synthetic-score-student",
        academic_year=2026,
        grade=3,
        semester=1,
        record_source="VOCATIONAL_TRAINING_RECORD",
        is_vocational_training_semester=True,
        verification_status="USER_VERIFIED",
    )
    session.add_all([home_record, vocational_record])
    session.flush()
    session.add_all(
        [
            StudentCourseRecord(
                academic_record_id=home_record.id,
                subject_name="합성 원적교 과목",
                raw_score=90,
                extraction_method="MANUAL_TEST",
                user_verified=True,
            ),
            StudentCourseRecord(
                academic_record_id=vocational_record.id,
                subject_name="합성 위탁 과목",
                raw_score_label="P",
                extraction_method="MANUAL_TEST",
                user_verified=True,
            ),
        ]
    )
    session.flush()

    decision = evaluate_published_score_inputs(
        session,
        track.id,
        "synthetic-score-student",
        _eligible_decision(),
    )

    assert decision.status is ScoreInputStatus.READY
    assert [record.record_source for record in decision.records] == ["HOME_SCHOOL_RECORD"]
    assert decision.trace.selected_terms[0].subjects == ("합성 원적교 과목",)


def _eligible_decision() -> EligibilityDecision:
    return EligibilityDecision(
        status=EligibilityStatus.ELIGIBLE,
        reason_code="SYNTHETIC_ELIGIBLE",
        matched_case_id="synthetic_case",
        missing_facts=(),
        trace=EligibilityTrace(
            rule_id="synthetic-eligibility",
            rule_version="synthetic-v1",
            conditions=(),
        ),
    )
