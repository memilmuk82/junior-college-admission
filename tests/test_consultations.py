from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models import (
    AdmissionEligibilityRule,
    AdmissionResultPublished,
    AdmissionResultPublishedBatch,
    AdmissionResultRawBatch,
    AdmissionResultStagingBatch,
    AdmissionResultStagingRow,
    AdmissionRound,
    AdmissionTrack,
    Campus,
    GradeSourceScopeRule,
    Institution,
    Program,
    RuleReview,
    ScoreRule,
    SourceCitation,
    SourceDocument,
    SourceDocumentPage,
    StudentAcademicRecord,
    StudentCourseRecord,
)
from app.services.admission_result_analysis import AdmissionResultAnalysisInput
from app.services.admission_results import AdmissionResultKey, HistoricalRuleReference
from app.services.consultations import (
    AdmissionResultComparisonStatus,
    ConsultationRequest,
    ConsultationStatus,
    classify_admission_result,
    run_consultation,
)
from app.services.eligibility import StudentFacts
from app.services.rule_admin import (
    RULE_CONTRACT_SCHEMA_VERSION,
    GoldenTestRunEvidence,
    record_golden_test_artifact,
    record_rule_audit,
    rule_contract_digest,
    rule_payload_digest,
)
from app.services.score_rule_schema import parse_score_rule_csv, score_rule_to_payload
from tests.test_score_rule_schema import _csv_bytes, _valid_row


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


def _target(session: Session) -> tuple[AdmissionTrack, SourceCitation]:
    institution = Institution(
        code="SYNTHETIC_U",
        name="합성 상담 전문대",
        institution_type="JUNIOR_COLLEGE",
    )
    session.add(institution)
    session.flush()
    campus = Campus(code="MAIN", institution_id=institution.id, name="합성 본교")
    session.add(campus)
    session.flush()
    program = Program(campus_id=campus.id, name="합성 학과")
    admission_round = AdmissionRound(
        institution_id=institution.id,
        academic_year=2027,
        code="EARLY_1",
        name="수시 1차",
    )
    session.add_all([program, admission_round])
    session.flush()
    track = AdmissionTrack(
        admission_round_id=admission_round.id,
        program_id=program.id,
        code="GENERAL",
        name="일반고 전형",
    )
    document = SourceDocument(
        academic_year=2027,
        institution_id=institution.id,
        campus_id=campus.id,
        document_type="FINAL_GUIDE",
        document_status="PUBLISHED",
        published_at=datetime(2026, 7, 13, tzinfo=UTC),
        file_hash="9" * 64,
        page_count=20,
        detected_years=[2027],
        year_consistency_status="CONSISTENT",
        verification_status="HUMAN_APPROVED",
    )
    session.add_all([track, document])
    session.flush()
    page = SourceDocumentPage(
        source_document_id=document.id,
        page_number=7,
        detected_academic_year=2027,
        verification_status="HUMAN_APPROVED",
    )
    session.add(page)
    session.flush()
    citation = SourceCitation(
        source_document_id=document.id,
        source_document_page_id=page.id,
        page_number=7,
        locator="합성 지원자격·성적 표",
        excerpt_digest="8" * 64,
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
        "golden_test_ref": "tests/synthetic-consultation-v1",
        "human_approved_at": datetime(2026, 7, 13, tzinfo=UTC),
    }


def _eligibility_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "cases": [
            {
                "case_id": "general_student",
                "when": {"fact": "final_school_type", "op": "eq", "value": "GENERAL"},
                "status": "ELIGIBLE",
                "reason_code": "GENERAL_ALLOWED",
            }
        ],
        "default": {"status": "INELIGIBLE", "reason_code": "TRACK_NOT_ALLOWED"},
    }


def _score_payload() -> dict[str, object]:
    row = _valid_row()
    row.update(
        {
            "home_grade_1_included": "TRUE",
            "home_grade_2_included": "FALSE",
            "vocational_grade_included": "FALSE",
            "vocational_semester_1_included": "FALSE",
            "semester_selection_method": "BEST_N",
            "best_semester_count": "1",
            "subject_selection_method": "ALL",
            "best_subject_count": "",
            "credit_weighted": "FALSE",
            "semester_rounding_mode": "",
            "semester_rounding_scale": "",
            "grade_rounding_mode": "",
            "grade_rounding_scale": "",
            "weighting_mode": "EQUAL",
            "grade_weight_1": "",
            "grade_weight_2": "",
            "grade_weight_3": "",
            "z_score_policy": "NOT_USED",
            "z_score_source": "",
            "z_score_table_code": "",
            "z_score_formula_version": "",
            "z_score_rounding_mode": "",
            "z_score_rounding_scale": "",
            "z_score_clip_min": "",
            "z_score_clip_max": "",
            "interview_ratio": "",
            "rounding_scale": "2",
            "maximum_score": "9",
        }
    )
    parsed = parse_score_rule_csv(_csv_bytes([row]))
    assert parsed.issues == ()
    return score_rule_to_payload(parsed.rows[0])


def _persist_published_rules(
    session: Session,
    rules: list[AdmissionEligibilityRule | GradeSourceScopeRule | ScoreRule],
) -> None:
    occurred_at = datetime(2026, 7, 13, tzinfo=UTC)
    rule_types = {
        AdmissionEligibilityRule: "ADMISSION_ELIGIBILITY_RULE",
        GradeSourceScopeRule: "GRADE_SOURCE_SCOPE_RULE",
        ScoreRule: "SCORE_RULE",
    }
    for rule in rules:
        rule.lifecycle_status = "VERIFIED"
        rule.independent_verified = True
        rule.golden_test_ref = None
        rule.human_approved_at = None
        session.add(rule)
        session.flush()
        rule_type = rule_types[type(rule)]
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
        for action in ("EXTRACTED", "VERIFIED"):
            details: dict[str, object] = {}
            if action == "VERIFIED":
                details = {
                    "independent_review_id": review.id,
                    "independent_reviewer_ref": review.reviewer_ref,
                }
            record_rule_audit(
                session,
                rule_type=rule_type,
                rule=rule,
                action=action,
                actor_ref="synthetic-admin",
                occurred_at=occurred_at,
                before_payload=rule.rule_payload,
                after_payload=rule.rule_payload,
                details=details,
            )
        artifact = record_golden_test_artifact(
            session,
            rule_type=rule_type,
            rule_id=rule.id,
            evidence=GoldenTestRunEvidence(
                runner_ref="synthetic-golden-runner",
                executed_at=occurred_at,
                suite_ref=f"tests/synthetic/{rule_type.lower()}-v1",
                suite_digest=hashlib.sha256(f"{rule_type}:synthetic-suite-v1".encode()).hexdigest(),
                independent_review_id=review.id,
                case_count=2,
                passed_case_count=2,
                failed_case_count=0,
            ),
        )
        rule.golden_test_ref = artifact.artifact_ref
        rule.golden_test_rule_type = rule_type
        rule.lifecycle_status = "PUBLISHED"
        rule.human_approved_at = occurred_at
        for action, details in (
            (
                "TESTED",
                {
                    "golden_test_ref": artifact.artifact_ref,
                    "golden_artifact_id": artifact.id,
                    "golden_artifact_digest": artifact.artifact_digest,
                    "golden_artifact_runner_ref": artifact.runner_ref,
                    "golden_artifact_suite_ref": artifact.suite_ref,
                    "golden_artifact_suite_digest": artifact.suite_digest,
                    "golden_artifact_case_count": artifact.case_count,
                    "independent_review_id": review.id,
                    "independent_reviewer_ref": review.reviewer_ref,
                },
            ),
            ("HUMAN_APPROVED", {}),
            ("PUBLISHED", {}),
        ):
            record_rule_audit(
                session,
                rule_type=rule_type,
                rule=rule,
                action=action,
                actor_ref="synthetic-admin",
                occurred_at=occurred_at,
                before_payload=rule.rule_payload,
                after_payload=rule.rule_payload,
                details=details,
            )
    session.flush()


def test_ineligible_consultation_stops_before_score_rules_and_records(session: Session) -> None:
    track, citation = _target(session)
    _persist_published_rules(
        session,
        [
            AdmissionEligibilityRule(
                version="eligibility-v1",
                rule_payload=_eligibility_payload(),
                **_metadata(track, citation),
            )
        ],
    )

    result = run_consultation(
        session,
        ConsultationRequest(
            student_id="synthetic-student",
            admission_track_id=track.id,
            facts=StudentFacts(final_school_type="VOCATIONAL"),
        ),
    )

    assert result.status is ConsultationStatus.ELIGIBILITY_BLOCKED
    assert result.eligibility.status.value == "INELIGIBLE"
    assert result.score is None
    assert result.score_input is None


def test_eligible_consultation_calculates_only_verified_rank_grade(session: Session) -> None:
    track, citation = _target(session)
    program = session.get(Program, track.program_id)
    assert program is not None
    program.code = "P1"
    score_payload = _score_payload()
    score_payload["attendance"] = {
        "attendance_included": True,
        "table_code": "SYNTHETIC_ATTENDANCE_V1",
        "source": "UNIVERSITY_OFFICIAL",
        "minor_event_conversion_unit": 3,
    }
    score_rule = ScoreRule(
        version="score-v1",
        rule_payload=score_payload,
        admission_year=2027,
        university_code="SYNTHETIC_U",
        university_name="합성 상담 전문대",
        campus_code="MAIN",
        admission_round="EARLY_1",
        admission_track_code="GENERAL",
        admission_track_name="일반고 전형",
        evidence_document_ref=citation.source_document_id,
        evidence_page=citation.page_number,
        evidence_location=citation.locator,
        source_status="FINAL_GUIDE",
        **_metadata(track, citation),
    )
    _persist_published_rules(
        session,
        [
            AdmissionEligibilityRule(
                version="eligibility-v1",
                rule_payload=_eligibility_payload(),
                **_metadata(track, citation),
            ),
            GradeSourceScopeRule(
                version="scope-v1",
                rule_payload={"schema_version": 1, "policy": "HOME_ONLY"},
                **_metadata(track, citation),
            ),
            score_rule,
        ],
    )
    record = StudentAcademicRecord(
        student_id="synthetic-student",
        academic_year=2025,
        grade=1,
        semester=1,
        record_source="HOME_SCHOOL_RECORD",
        verification_status="USER_VERIFIED",
    )
    session.add(record)
    session.flush()
    session.add_all(
        [
            StudentCourseRecord(
                academic_record_id=record.id,
                subject_group="KOREAN",
                subject_name="합성 국어",
                credits=Decimal("3"),
                rank_grade=Decimal("2"),
                extraction_method="MANUAL",
                user_verified=True,
            ),
            StudentCourseRecord(
                academic_record_id=record.id,
                subject_group="MATH",
                subject_name="미검증 수학",
                credits=Decimal("3"),
                rank_grade=Decimal("9"),
                extraction_method="MANUAL",
                user_verified=False,
            ),
        ]
    )
    session.flush()
    raw_batch = AdmissionResultRawBatch(
        source_code="SYNTHETIC_CONSULTATION_RESULTS",
        expected_academic_year=2027,
        collection_digest="7" * 64,
        page_count=1,
        row_count=1,
        policy_payload={"synthetic": True},
        status="COLLECTED",
        collected_at=datetime(2026, 7, 13, tzinfo=UTC),
    )
    session.add(raw_batch)
    session.flush()
    staging_batch = AdmissionResultStagingBatch(
        raw_batch_id=raw_batch.id,
        expected_academic_year=2027,
        status="READY",
        total_row_count=1,
        valid_row_count=1,
        error_row_count=0,
        validation_issues=[],
    )
    session.add(staging_batch)
    session.flush()
    staging_row = AdmissionResultStagingRow(
        staging_batch_id=staging_batch.id,
        source_row_number=1,
        academic_year=2027,
        university_code="SYNTHETIC_U",
        campus_code="MAIN",
        admission_round="EARLY_1",
        admission_track_code="GENERAL",
        program_code="P1",
        applicant_count=0,
        admitted_count=0,
        competition_rate=Decimal("0"),
        average_score=Decimal("2.5"),
        score_basis="RANK_GRADE",
        validation_status="VALID",
        validation_issues=[],
    )
    session.add(staging_row)
    session.flush()
    published_batch = AdmissionResultPublishedBatch(
        staging_batch_id=staging_batch.id,
        approved_by="synthetic-admin",
        approved_at=datetime(2026, 7, 13, tzinfo=UTC),
        confirmed_row_count=1,
    )
    session.add(published_batch)
    session.flush()
    session.add(
        AdmissionResultPublished(
            published_batch_id=published_batch.id,
            staging_row_id=staging_row.id,
            academic_year=2027,
            university_code="SYNTHETIC_U",
            campus_code="MAIN",
            admission_round="EARLY_1",
            admission_track_code="GENERAL",
            program_code="P1",
            publication_version="synthetic-result-v1",
            lifecycle_status="PUBLISHED",
            applicant_count=0,
            admitted_count=0,
            competition_rate=Decimal("0"),
            average_score=Decimal("2.5"),
            score_basis="RANK_GRADE",
            score_rule_id=score_rule.id,
            score_rule_version=score_rule.version,
            score_rule_academic_year=2027,
        )
    )
    session.flush()

    result = run_consultation(
        session,
        ConsultationRequest(
            student_id="synthetic-student",
            admission_track_id=track.id,
            facts=StudentFacts(final_school_type="GENERAL"),
            admission_result_year=2027,
        ),
    )

    assert result.status is ConsultationStatus.READY
    assert result.score is None
    assert result.reflected_grade is not None
    assert result.reflected_grade.display_average_grade == Decimal("2.00")
    assert result.reflected_grade.trace.rule_version == "score-v1"
    assert result.score_selection is not None
    assert result.score_input is not None
    assert result.score_selection.trace.selected_semesters[0].selected_course_ids == (
        result.score_input.records[0].courses[0].course_record_id,
    )
    assert result.admission_result.status is AdmissionResultComparisonStatus.COMPARABLE
    assert result.admission_result.result is not None
    assert result.admission_result.result.applicant_count == 0
    assert result.admission_result.result.competition_rate == Decimal("0")
    assert any("출결 배점은 평균등급과 분리" in warning for warning in result.warnings)


def test_admission_result_is_directly_compared_only_with_same_rule_and_year() -> None:
    key = AdmissionResultKey(2027, "SYNTHETIC_U", "MAIN", "EARLY_1", "GENERAL", "P1")
    published = AdmissionResultAnalysisInput(
        key=key,
        publication_version="published-v1",
        applicant_count=0,
        admitted_count=0,
        competition_rate=Decimal("0"),
        highest_score=None,
        average_score=Decimal("2.5"),
        lowest_score=None,
        score_basis="RANK_GRADE",
        historical_rule=HistoricalRuleReference("score-rule", "score-v1", 2027),
    )

    matched = classify_admission_result(
        published,
        current_rule_id="score-rule",
        current_rule_version="score-v1",
        current_academic_year=2027,
    )
    reference_only = classify_admission_result(
        published,
        current_rule_id="different-rule",
        current_rule_version="score-v2",
        current_academic_year=2027,
    )
    different_scale = classify_admission_result(
        replace(published, score_basis="POINT_SCORE"),
        current_rule_id="score-rule",
        current_rule_version="score-v1",
        current_academic_year=2027,
    )

    assert matched.status is AdmissionResultComparisonStatus.COMPARABLE
    assert matched.result is not None
    assert matched.result.applicant_count == 0
    assert matched.result.competition_rate == Decimal("0")
    assert reference_only.status is AdmissionResultComparisonStatus.REFERENCE_ONLY
    assert different_scale.status is AdmissionResultComparisonStatus.INCOMPATIBLE_SCALE
    assert reference_only.display_average_grade == Decimal("2.5")
    assert different_scale.display_average_grade is None
