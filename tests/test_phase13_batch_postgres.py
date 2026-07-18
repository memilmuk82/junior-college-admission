from __future__ import annotations

from collections.abc import Iterator
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session
from werkzeug.datastructures import MultiDict

import app.services.consultations as consultation_service
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
    Program,
    ScoreRule,
    SourceCitation,
    StudentAcademicRecord,
    StudentCourseRecord,
)
from app.services.consultation_forms import parse_consultation_form
from app.services.consultations import (
    AdmissionResultComparisonStatus,
    BatchConsultationRequest,
    ConsultationError,
    ConsultationItemStatus,
    list_consultation_programs,
    run_batch_consultation,
)
from tests.test_consultations import (
    _eligibility_payload,
    _metadata,
    _persist_published_rules,
    _score_payload,
    _target,
)


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


def _track(
    session: Session,
    *,
    program: Program,
    admission_round: AdmissionRound,
    code: str,
    name: str,
) -> AdmissionTrack:
    track = AdmissionTrack(
        admission_round_id=admission_round.id,
        program_id=program.id,
        code=code,
        name=name,
    )
    session.add(track)
    session.flush()
    return track


def _score_rule(
    track: AdmissionTrack,
    citation: SourceCitation,
    *,
    program_code: str,
    payload: dict[str, object],
) -> ScoreRule:
    return ScoreRule(
        version=f"score-{track.code.lower()}-v1",
        rule_payload=payload,
        admission_year=2027,
        university_code="SYNTHETIC_U",
        university_name="합성 상담 전문대",
        campus_code="MAIN",
        admission_round="EARLY_1",
        admission_track_code=track.code,
        admission_track_name=track.name,
        evidence_document_ref=citation.source_document_id,
        evidence_page=citation.page_number,
        evidence_location=citation.locator,
        source_status="FINAL_GUIDE",
        change_reason="Phase 13 PostgreSQL 배치 합성 검증",
        **_metadata(track, citation),
    )


def _publish_complete_track(
    session: Session,
    track: AdmissionTrack,
    citation: SourceCitation,
    *,
    program_code: str,
    scope_policy: str,
    payload: dict[str, object],
) -> ScoreRule:
    score_rule = _score_rule(
        track,
        citation,
        program_code=program_code,
        payload=payload,
    )
    _persist_published_rules(
        session,
        [
            AdmissionEligibilityRule(
                version=f"eligibility-{track.code.lower()}-v1",
                rule_payload=_eligibility_payload(),
                **_metadata(track, citation),
            ),
            GradeSourceScopeRule(
                version=f"scope-{track.code.lower()}-v1",
                rule_payload={"schema_version": 1, "policy": scope_policy},
                **_metadata(track, citation),
            ),
            score_rule,
        ],
    )
    return score_rule


def _student_records(session: Session) -> None:
    for source, semester, grade_value in (
        ("HOME_SCHOOL_RECORD", 1, "4"),
        ("VOCATIONAL_TRAINING_RECORD", 2, "1"),
    ):
        record = StudentAcademicRecord(
            student_id="synthetic-batch-student",
            academic_year=2025,
            grade=1,
            semester=semester,
            record_source=source,
            is_vocational_training_semester=source == "VOCATIONAL_TRAINING_RECORD",
            verification_status="USER_VERIFIED",
        )
        session.add(record)
        session.flush()
        session.add(
            StudentCourseRecord(
                academic_record_id=record.id,
                subject_group="SYNTHETIC",
                subject_name=f"합성 {source}",
                credits=Decimal("3"),
                rank_grade=Decimal(grade_value),
                extraction_method="MANUAL",
                user_verified=True,
            )
        )
    session.flush()


def _publish_result(session: Session, track: AdmissionTrack, score_rule: ScoreRule) -> None:
    raw = AdmissionResultRawBatch(
        source_code="PHASE13_BATCH_SYNTHETIC",
        expected_academic_year=2027,
        collection_digest="6" * 64,
        page_count=1,
        row_count=1,
        policy_payload={"synthetic": True},
        status="COLLECTED",
        collected_at=datetime(2026, 7, 18, tzinfo=UTC),
    )
    session.add(raw)
    session.flush()
    staging = AdmissionResultStagingBatch(
        raw_batch_id=raw.id,
        expected_academic_year=2027,
        status="READY",
        total_row_count=1,
        valid_row_count=1,
        error_row_count=0,
        validation_issues=[],
    )
    session.add(staging)
    session.flush()
    row = AdmissionResultStagingRow(
        staging_batch_id=staging.id,
        source_row_number=1,
        academic_year=2027,
        university_code="SYNTHETIC_U",
        campus_code="MAIN",
        admission_round="EARLY_1",
        admission_track_code=track.code,
        program_code="P_BATCH",
        applicant_count=30,
        admitted_count=10,
        competition_rate=Decimal("3.00"),
        average_score=Decimal("3.20"),
        score_basis="RANK_GRADE",
        validation_status="VALID",
        validation_issues=[],
    )
    session.add(row)
    session.flush()
    published_batch = AdmissionResultPublishedBatch(
        staging_batch_id=staging.id,
        approved_by="synthetic-admin",
        approved_at=datetime(2026, 7, 18, tzinfo=UTC),
        confirmed_row_count=1,
    )
    session.add(published_batch)
    session.flush()
    session.add(
        AdmissionResultPublished(
            published_batch_id=published_batch.id,
            staging_row_id=row.id,
            academic_year=2027,
            university_code="SYNTHETIC_U",
            campus_code="MAIN",
            admission_round="EARLY_1",
            admission_track_code=track.code,
            program_code="P_BATCH",
            publication_version="phase13-synthetic-v1",
            lifecycle_status="PUBLISHED",
            applicant_count=30,
            admitted_count=10,
            competition_rate=Decimal("3.00"),
            average_score=Decimal("3.20"),
            score_basis="RANK_GRADE",
            score_rule_id=score_rule.id,
            score_rule_version=score_rule.version,
            score_rule_academic_year=2027,
        )
    )
    session.flush()


def _batch_form(*program_ids: str) -> MultiDict[str, str]:
    form = MultiDict(
        (
            ("student_id", "synthetic-batch-student"),
            ("academic_year", "2027"),
            ("home_school_type", "GENERAL"),
            ("final_school_type", "GENERAL"),
            ("graduation_status", "EXPECTED"),
            ("vocational_training_status", "PARTICIPATING"),
            ("vocational_training_semesters", "1"),
            ("transferred", "FALSE"),
            ("ged", "FALSE"),
            ("admission_result_year", "2027"),
        )
    )
    for program_id in program_ids:
        form.add("program_ids", program_id)
    return form


def test_postgres_batch_expansion_is_ordered_isolated_and_eligibility_first(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    home_track, citation = _target(session)
    program = session.get(Program, home_track.program_id)
    admission_round = session.get(AdmissionRound, home_track.admission_round_id)
    assert program is not None and admission_round is not None
    program.code = "P_BATCH"
    vocational_track = _track(
        session,
        program=program,
        admission_round=admission_round,
        code="VOCATIONAL",
        name="위탁 포함 전형",
    )
    home_payload = deepcopy(_score_payload())
    home_payload["semester_selection"] = {
        "method": "ALL",
        "scope": "GLOBAL",
        "best_count": None,
    }
    # 이 배점 변환은 maximum_score 범위를 벗어나지만 평균등급 경로를 막아서는 안 된다.
    home_payload["score_transform"] = {
        "mode": "LINEAR",
        "base": "100",
        "multiplier": "100",
    }
    home_score_rule = _publish_complete_track(
        session,
        home_track,
        citation,
        program_code="P_BATCH",
        scope_policy="HOME_ONLY",
        payload=home_payload,
    )
    vocational_payload = deepcopy(home_payload)
    vocational_payload["source_inclusion"] = {
        **vocational_payload["source_inclusion"],  # type: ignore[dict-item]
        "vocational_grade": True,
        "vocational_semester_2": True,
    }
    _publish_complete_track(
        session,
        vocational_track,
        citation,
        program_code="P_BATCH",
        scope_policy="VOCATIONAL_INCLUDED",
        payload=vocational_payload,
    )

    campus = session.get(Campus, program.campus_id)
    assert campus is not None
    ineligible_program = Program(campus_id=campus.id, name="합성 자격미달 학과", code="P_NO")
    preparing_program = Program(campus_id=campus.id, name="합성 준비중 학과", code="P_WAIT")
    error_program = Program(campus_id=campus.id, name="합성 오류격리 학과", code="P_ERROR")
    no_track_program = Program(campus_id=campus.id, name="합성 전형없음 학과", code="P_ZERO")
    session.add_all([ineligible_program, preparing_program, error_program, no_track_program])
    session.flush()
    ineligible_track = _track(
        session,
        program=ineligible_program,
        admission_round=admission_round,
        code="BLOCKED",
        name="자격미달 전형",
    )
    _persist_published_rules(
        session,
        [
            AdmissionEligibilityRule(
                version="eligibility-blocked-v1",
                rule_payload={
                    "schema_version": 1,
                    "cases": [],
                    "default": {
                        "status": "INELIGIBLE",
                        "reason_code": "SYNTHETIC_BLOCKED",
                    },
                },
                **_metadata(ineligible_track, citation),
            )
        ],
    )
    _track(
        session,
        program=preparing_program,
        admission_round=admission_round,
        code="PREPARING",
        name="규칙 준비중 전형",
    )
    error_track = _track(
        session,
        program=error_program,
        admission_round=admission_round,
        code="ERROR",
        name="오류격리 전형",
    )
    _publish_complete_track(
        session,
        error_track,
        citation,
        program_code="P_ERROR",
        scope_policy="HOME_ONLY",
        payload=deepcopy(_score_payload()),
    )
    round_2028 = AdmissionRound(
        institution_id=admission_round.institution_id,
        academic_year=2028,
        code="EARLY_1_2028",
        name="2028 수시 1차",
    )
    future_program = Program(campus_id=campus.id, name="합성 2028 학과", code="P_2028")
    session.add_all([round_2028, future_program])
    session.flush()
    _track(
        session,
        program=future_program,
        admission_round=round_2028,
        code="FUTURE",
        name="2028 전형",
    )
    _student_records(session)
    _publish_result(session, home_track, home_score_rule)

    listed_ids = tuple(item.program_id for item in list_consultation_programs(session, 2027))
    assert program.id in listed_ids
    assert preparing_program.id in listed_ids
    assert no_track_program.id not in listed_ids
    assert future_program.id not in listed_ids

    parsed = parse_consultation_form(
        _batch_form(ineligible_program.id, program.id, preparing_program.id, error_program.id)
    )
    assert isinstance(parsed.request, BatchConsultationRequest)
    assert parsed.request.program_ids == (
        ineligible_program.id,
        program.id,
        preparing_program.id,
        error_program.id,
    )

    original_run = consultation_service.run_consultation

    def isolated_failure(session_arg, request_arg, **kwargs):  # type: ignore[no-untyped-def]
        if request_arg.admission_track_id == error_track.id:
            raise ValueError("합성 항목 오류")
        return original_run(session_arg, request_arg, **kwargs)

    monkeypatch.setattr(consultation_service, "run_consultation", isolated_failure)
    result = run_batch_consultation(session, parsed.request)

    assert tuple(item.program.program_id for item in result.items) == (
        ineligible_program.id,
        program.id,
        program.id,
        preparing_program.id,
        error_program.id,
    )
    blocked = result.items[0]
    assert blocked.result is not None
    assert blocked.result.eligibility.status.value == "INELIGIBLE"
    assert blocked.result.score_input is None
    assert blocked.result.score_selection is None
    assert blocked.result.reflected_grade is None
    assert result.items[3].status is ConsultationItemStatus.PREPARING
    assert result.items[4].status is ConsultationItemStatus.ERROR

    evaluated = [item.result for item in result.items[1:3]]
    assert all(item is not None and item.score is None for item in evaluated)
    grades = {
        item.target.admission_track_code: item.reflected_grade.display_average_grade
        for item in evaluated
        if item is not None and item.reflected_grade is not None
    }
    assert grades == {"GENERAL": Decimal("4.00"), "VOCATIONAL": Decimal("2.50")}
    home_result = evaluated[0]
    assert home_result is not None
    assert home_result.admission_result.status is AdmissionResultComparisonStatus.COMPARABLE
    assert home_result.admission_result.result is not None
    assert home_result.admission_result.result.average_score == Decimal("3.2000")
    vocational_result = evaluated[1]
    assert vocational_result is not None
    assert (
        vocational_result.admission_result.status is AdmissionResultComparisonStatus.NOT_AVAILABLE
    )

    with pytest.raises(ConsultationError, match="허용되지 않은 ID"):
        run_batch_consultation(
            session,
            BatchConsultationRequest(
                "synthetic-batch-student",
                (future_program.id,),
                2027,
                parsed.request.facts,
                2027,
            ),
        )
