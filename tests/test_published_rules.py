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
    SourceCitation,
    SourceDocument,
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
    RuleSchemaError,
    StudentFacts,
)
from app.services.published_rules import (
    PublishedRuleNotFound,
    evaluate_published_eligibility,
    load_published_multiple_application_rule,
)
from app.services.score_inputs import ScoreInputStatus, evaluate_published_score_inputs


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
    institution = Institution(name="합성 규칙 전문대", institution_type="JUNIOR_COLLEGE")
    session.add(institution)
    session.flush()
    campus = Campus(institution_id=institution.id, name="합성 캠퍼스")
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
    citation = SourceCitation(
        source_document_id=document.id,
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


def test_published_eligibility_rule_is_loaded_and_draft_is_ignored(
    session: Session,
) -> None:
    track, citation = _track_and_citation(session)
    session.add_all(
        [
            AdmissionEligibilityRule(
                version="synthetic-published-v1",
                rule_payload=_eligibility_payload(),
                **_metadata(track, citation),
            ),
            AdmissionEligibilityRule(
                admission_track_id=track.id,
                version="synthetic-draft-v2",
                lifecycle_status="DRAFT",
                rule_payload={"invalid_draft_is_not_loaded": True},
                independent_verified=False,
            ),
        ]
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
    session.add(
        AdmissionEligibilityRule(
            version="synthetic-invalid-v1",
            rule_payload={"expression": "not executable"},
            **_metadata(track, citation),
        )
    )
    session.flush()

    with pytest.raises(RuleSchemaError):
        evaluate_published_eligibility(session, track.id, StudentFacts())


@pytest.mark.parametrize(
    "model",
    [
        AdmissionEligibilityRule,
        MultipleApplicationRule,
        DisqualificationRule,
        GradeSourceScopeRule,
    ],
)
def test_database_rejects_two_published_versions_per_track(
    session: Session,
    model: type[
        AdmissionEligibilityRule
        | MultipleApplicationRule
        | DisqualificationRule
        | GradeSourceScopeRule
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


def test_multiple_application_rule_has_separate_loader(session: Session) -> None:
    track, citation = _track_and_citation(session)
    session.add(
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
        )
    )
    session.flush()

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
    session.add(rule)
    session.flush()

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
    session.add(
        GradeSourceScopeRule(
            version="synthetic-scope-v1",
            rule_payload={"schema_version": 1, "policy": "HOME_ONLY"},
            **_metadata(track, citation),
        )
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
