from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app import create_app
from app.models import (
    AdmissionEligibilityRule,
    AdmissionRound,
    AdmissionTrack,
    Campus,
    GradeSourceScopeRule,
    Institution,
    Program,
    ScoreRule,
    SourceCitation,
    SourceDocument,
    StudentAcademicRecord,
    StudentCourseRecord,
)
from tests.test_consultations import (
    _eligibility_payload,
    _metadata,
    _score_payload,
    _target,
)


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _form(track_id: str, csrf_token: str) -> dict[str, str]:
    return {
        "csrf_token": csrf_token,
        "student_id": "synthetic-student",
        "admission_track_id": track_id,
        "home_school_type": "GENERAL",
        "final_school_type": "GENERAL",
        "graduation_status": "EXPECTED",
        "vocational_training_status": "PARTICIPATING",
        "vocational_training_semesters": "1",
        "vocational_training_hours": "",
        "vocational_training_months": "",
        "transferred": "FALSE",
        "ged": "FALSE",
        "admission_result_year": "2026",
        "consultation_note": "합성 교사용 상담 메모",
    }


def _seed(session: Session) -> str:
    track, citation = _target(session)
    program = session.get(Program, track.program_id)
    assert program is not None
    program.code = "P1"
    session.add_all(
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
            ScoreRule(
                version="score-v1",
                rule_payload=_score_payload(),
                admission_year=2027,
                university_code="SYNTHETIC_U",
                university_name="합성 상담 전문대",
                campus_code="MAIN",
                admission_round="EARLY_1",
                admission_track_code="GENERAL",
                admission_track_name="일반고 전형",
                source_status="FINAL_GUIDE",
                change_reason="합성 E2E 초기 규칙",
                **_metadata(track, citation),
            ),
        ]
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
    session.add(
        StudentCourseRecord(
            academic_record_id=record.id,
            subject_group="KOREAN",
            subject_name="합성 국어",
            credits=Decimal("3"),
            rank_grade=Decimal("2"),
            extraction_method="MANUAL",
            user_verified=True,
        )
    )
    session.commit()
    return track.id


def _cleanup(session: Session, track_id: str) -> None:
    track = session.get(AdmissionTrack, track_id)
    assert track is not None
    admission_round = session.get(AdmissionRound, track.admission_round_id)
    program = session.get(Program, track.program_id)
    assert admission_round is not None and program is not None
    campus = session.get(Campus, program.campus_id)
    institution = session.get(Institution, admission_round.institution_id)
    assert campus is not None and institution is not None
    document = session.scalar(select(SourceDocument).where(SourceDocument.file_hash == "9" * 64))
    assert document is not None
    session.execute(
        delete(StudentCourseRecord).where(
            StudentCourseRecord.academic_record_id.in_(
                select(StudentAcademicRecord.id).where(
                    StudentAcademicRecord.student_id == "synthetic-student"
                )
            )
        )
    )
    session.execute(
        delete(StudentAcademicRecord).where(StudentAcademicRecord.student_id == "synthetic-student")
    )
    for model in (AdmissionEligibilityRule, GradeSourceScopeRule, ScoreRule):
        session.execute(delete(model).where(model.admission_track_id == track_id))
    session.execute(delete(SourceCitation).where(SourceCitation.source_document_id == document.id))
    session.execute(delete(SourceDocument).where(SourceDocument.id == document.id))
    session.execute(delete(AdmissionTrack).where(AdmissionTrack.id == track.id))
    session.execute(delete(AdmissionRound).where(AdmissionRound.id == admission_round.id))
    session.execute(delete(Program).where(Program.id == program.id))
    session.execute(delete(Campus).where(Campus.id == campus.id))
    session.execute(delete(Institution).where(Institution.id == institution.id))
    session.commit()


def test_consultation_requires_admin_auth_and_renders_separate_print_views(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine) as database_session:
        track_id = _seed(database_session)

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "ADMIN_USERNAME": "synthetic-admin",
            "ADMIN_PASSWORD_HASH": generate_password_hash("synthetic-password"),
        }
    )
    client = app.test_client()
    blocked = client.get("/admin/consultations/new")
    assert blocked.status_code == 302
    assert "/admin/login" in blocked.headers["Location"]

    login_page = client.get("/admin/login")
    client.post(
        "/admin/login",
        data={
            "csrf_token": _csrf(login_page.get_data(as_text=True)),
            "username": "synthetic-admin",
            "password": "synthetic-password",
        },
    )
    form_page = client.get("/admin/consultations/new")
    assert form_page.status_code == 200
    assert form_page.headers["Cache-Control"] == "no-store, max-age=0"
    assert "단계형 상담 시작" in form_page.get_data(as_text=True)

    submitted = client.post(
        "/admin/consultations/new",
        data=_form(track_id, _csrf(form_page.get_data(as_text=True))),
    )
    body = submitted.get_data(as_text=True)
    assert submitted.status_code == 200
    assert "지원자격 확인 완료" in body
    assert "2.00" in body
    assert "직접 비교하지 않습니다" in body or "게시 승인된 동일 업무키" in body
    assert all(word not in body for word in ("합격 확률", "안정", "적정", "소신", "위험"))

    student_print = client.post(
        "/admin/consultations/print/student",
        data=_form(track_id, _csrf(body)),
    )
    student_body = student_print.get_data(as_text=True)
    assert student_print.status_code == 200
    assert "학생용 상담 결과" in student_body
    assert "합성 교사용 상담 메모" not in student_body
    assert "조건 평가 trace" not in student_body

    teacher_print = client.post(
        "/admin/consultations/print/teacher",
        data=_form(track_id, _csrf(body)),
    )
    teacher_body = teacher_print.get_data(as_text=True)
    assert teacher_print.status_code == 200
    assert "교사용 상담 결과" in teacher_body
    assert "합성 교사용 상담 메모" in teacher_body
    assert "조건 평가 trace" in teacher_body
    assert "성적 범위 trace" in teacher_body
    assert "계산 trace" in teacher_body

    with Session(postgres_engine) as database_session:
        _cleanup(database_session, track_id)
