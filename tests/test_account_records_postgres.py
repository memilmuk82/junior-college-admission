from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session

from app import create_app
from app.models import (
    SavedConsultation,
    StudentAcademicRecord,
    StudentCourseRecord,
    UserAccount,
    UserAccountAuditEvent,
)
from app.services.membership import bootstrap_admin


def _active_user(admin: UserAccount, suffix: str, role: str) -> UserAccount:
    return UserAccount(
        actor_ref=f"user:phase14-account-{suffix}",
        login_name=f"phase14-account-{suffix}",
        email=f"{suffix}@phase14-account.invalid",
        display_name=f"합성 {suffix}",
        password_hash="synthetic-password-hash",
        role=role,
        status="ACTIVE",
        auth_version=1,
        approved_at=datetime.now(UTC),
        approved_by_user_id=admin.id,
    )


def _record(
    session: Session,
    *,
    student_id: str,
    owner: str | None,
    manager: str | None,
    subject: str,
) -> tuple[StudentAcademicRecord, StudentCourseRecord]:
    record = StudentAcademicRecord(
        student_id=student_id,
        owner_user_account_id=owner,
        managed_by_user_account_id=manager,
        academic_year=2026,
        grade=1,
        semester=1,
        record_source="HOME_SCHOOL_RECORD",
        is_vocational_training_semester=False,
        verification_status="USER_VERIFIED",
    )
    session.add(record)
    session.flush()
    course = StudentCourseRecord(
        academic_record_id=record.id,
        subject_group="국어",
        subject_name=subject,
        credits=Decimal("4"),
        raw_score=Decimal("0"),
        course_mean=Decimal("70"),
        standard_deviation=Decimal("12"),
        achievement_level="B",
        enrollment_count=120,
        rank_grade=Decimal("2"),
        extraction_method="ANONYMOUS_CONFIRMED",
        user_verified=True,
    )
    session.add(course)
    session.flush()
    return record, course


def _consultation(
    session: Session,
    *,
    calculation_id: str,
    owner: str | None,
    manager: str | None,
    student_reference: str,
    student_profile: str = "VOCATIONAL_CURRENT",
    include_reference_result: bool = False,
) -> SavedConsultation:
    reference_results = (
        [
            {
                "result_academic_year": 2026,
                "admission_round_code": "SUSI-1",
                "admission_track_code": "SPECIAL-GENERAL-HS",
                "day_night": "DAY",
                "capacity": 20,
                "applicant_count": 195,
                "admitted_count": 20,
                "competition_rate": "9.7500",
                "best_score": "58.0000",
                "average_score": "65.0600",
                "cutoff_score": "70.0000",
                "score_basis": "POINT_SCORE",
                "score_basis_label": "수능 백분위·배점(참고용)",
                "score_direction": "HIGHER_IS_BETTER",
                "is_direct_grade_comparison_allowed": False,
                "publication_version": "synthetic-2026-v1",
                "source_reference": "합성 공개자료",
            }
        ]
        if include_reference_result
        else []
    )
    payload = {
        "schema_version": 3,
        "academic_year": 2027,
        "results": [
            {
                "target": {
                    "academic_year": 2027,
                    "institution_name": "동양미래대학교",
                    "campus_name": "본교",
                    "program_name": "호텔관광학과",
                    "admission_round_name": "수시 1차",
                    "admission_track_name": "일반고 특별전형",
                },
                "item_status": "READY",
                "eligibility": {
                    "status": "ELIGIBLE",
                    "reason_code": "SYNTHETIC_ELIGIBLE",
                    "missing_fact_names": [],
                    "rule_version": "synthetic-v1",
                },
                "average_grade": {
                    "unrounded_average_grade": "2",
                    "final_average_grade": "2.00",
                    "display_average_grade": "2.00",
                    "grade_scale": "RANK_GRADE",
                    "rule_version": "synthetic-v1",
                    "weighting_mode": "EQUAL",
                    "rounding_mode": "ROUND_HALF_UP",
                    "rounding_scale": 2,
                },
                "admission_result": {"status": "NOT_AVAILABLE"},
                "reference_results": reference_results,
                "evidence": [],
                "warnings": [],
            }
        ],
    }
    consultation = SavedConsultation(
        calculation_id=calculation_id,
        student_reference=student_reference,
        owner_user_account_id=owner,
        managed_by_user_account_id=manager,
        academic_year=2027,
        student_profile=student_profile,
        selected_targets=[
            {
                "program_id": "synthetic-program",
                "institution_name": "동양미래대학교",
                "campus_name": "본교",
                "program_name": "호텔관광학과",
            }
        ],
        result_snapshot=payload,
        student_print_snapshot={"audience": "STUDENT", "result": payload},
        teacher_print_snapshot={"audience": "TEACHER", "result": payload},
    )
    session.add(consultation)
    session.flush()
    return consultation


def _login_as(client, user: UserAccount) -> str:  # type: ignore[no-untyped-def]
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = user.id
        browser_session["auth_version"] = user.auth_version
        browser_session["csrf_token"] = "phase14-account-csrf"
        browser_session["admin_csrf_token"] = "phase14-account-csrf"
    return "phase14-account-csrf"


def test_account_records_edit_and_consultation_history_are_owner_scoped(
    postgres_engine: Engine,
    tmp_path: Path,
) -> None:
    created_user_ids: tuple[str, ...] = ()
    record_ids: tuple[str, ...] = ()
    try:
        with Session(postgres_engine, expire_on_commit=False) as database_session:
            admin = bootstrap_admin(
                database_session,
                login_name="phase14-account-admin",
                password_hash="synthetic-password-hash",
                occurred_at=datetime.now(UTC),
            )
            student = _active_user(admin, "student", "STUDENT")
            other_student = _active_user(admin, "other-student", "STUDENT")
            teacher = _active_user(admin, "teacher", "TEACHER")
            other_teacher = _active_user(admin, "other-teacher", "TEACHER")
            database_session.add_all((student, other_student, teacher, other_teacher))
            database_session.flush()
            own_record, own_course = _record(
                database_session,
                student_id=f"account:{student.id}",
                owner=student.id,
                manager=None,
                subject="학생 본인 과목",
            )
            other_record, _ = _record(
                database_session,
                student_id=f"account:{other_student.id}",
                owner=other_student.id,
                manager=None,
                subject="다른 학생 과목",
            )
            student_consultation = _consultation(
                database_session,
                calculation_id="phase15-student-consultation",
                owner=student.id,
                manager=None,
                student_reference=f"account:{student.id}",
                include_reference_result=True,
            )
            graduate_consultation = _consultation(
                database_session,
                calculation_id="phase17-graduate-student-consultation",
                owner=student.id,
                manager=None,
                student_reference=f"account:{student.id}",
                student_profile="GENERAL_GRADUATE",
            )
            teacher_consultation = _consultation(
                database_session,
                calculation_id="phase14-teacher-consultation",
                owner=None,
                manager=teacher.id,
                student_reference="teacher-managed-synthetic-student",
            )
            other_consultation = _consultation(
                database_session,
                calculation_id="phase14-other-teacher-consultation",
                owner=None,
                manager=other_teacher.id,
                student_reference="other-teacher-managed-student",
            )
            database_session.commit()
            created_user_ids = (
                student.id,
                other_student.id,
                teacher.id,
                other_teacher.id,
                admin.id,
            )
            record_ids = (own_record.id, other_record.id)

        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret",
                "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
                "TEMP_UPLOAD_ROOT": str(tmp_path / "uploads"),
            }
        )
        student_client = app.test_client()
        csrf = _login_as(student_client, student)
        page = student_client.get("/account/records")
        body = page.get_data(as_text=True)
        assert page.status_code == 200
        assert "학생 본인 과목" in body
        assert "다른 학생 과목" not in body
        assert "공개 참고결과 1건" in body
        assert "65.0600" in body
        assert "직접 비교 불가" in body
        saved_print = student_client.get(
            f"/account/consultations/{student_consultation.id}/print/student"
        )
        assert saved_print.status_code == 200
        saved_print_body = saved_print.get_data(as_text=True)
        assert "2026학년도" in saved_print_body
        assert "수능 백분위·배점(참고용)" in saved_print_body
        assert "65.0600" in saved_print_body
        cloned = student_client.get(f"/account/consultations/{student_consultation.id}/clone")
        assert cloned.status_code == 200
        cloned_body = cloned.get_data(as_text=True)
        assert "학생 본인 과목" in cloned_body
        assert "저장 상담을 새 입력으로 복제했습니다." in cloned_body
        assert cloned_body.count("data-score-row") == 60
        assert 'name="rows-1-subject_name"' in cloned_body
        assert 'name="rows-59-subject_name"' in cloned_body
        assert 'value="VOCATIONAL_CURRENT" checked' in cloned_body
        assert 'value="GENERAL_GRADUATE"' in cloned_body
        graduate_clone = student_client.get(
            f"/account/consultations/{graduate_consultation.id}/clone"
        )
        assert graduate_clone.status_code == 200
        graduate_clone_body = graduate_clone.get_data(as_text=True)
        assert 'value="GENERAL_GRADUATE" checked' in graduate_clone_body
        assert (
            'name="rows-40-record_source" type="hidden" '
            'value="HOME_SCHOOL_RECORD"' in graduate_clone_body
        )
        assert (
            'name="rows-40-is_vocational_training_semester" type="hidden" value="FALSE"'
            in graduate_clone_body
        )
        clone_with_added_course = student_client.post(
            "/calculate/input",
            data={
                "csrf_token": csrf,
                "input_mode": "manual",
                "record_source": "HOME_SCHOOL_RECORD",
                "rows-0-academic_year": "2026",
                "rows-0-grade": "1",
                "rows-0-semester": "1",
                "rows-0-subject_group": "국어",
                "rows-0-subject_name": "학생 본인 과목",
                "rows-0-credits": "4",
                "rows-0-rank_grade": "2",
                "rows-1-academic_year": "2026",
                "rows-1-grade": "1",
                "rows-1-semester": "1",
                "rows-1-subject_group": "수학",
                "rows-1-subject_name": "복제 뒤 추가한 합성 과목",
                "rows-1-credits": "3",
                "rows-1-rank_grade": "3",
            },
            follow_redirects=False,
        )
        assert clone_with_added_course.status_code == 302
        other_logged_client = app.test_client()
        _login_as(other_logged_client, other_student)
        with other_logged_client.session_transaction() as other_browser_session:
            other_browser_session["anonymous_calculation_owner"] = (
                "synthetic-different-anonymous-owner"
            )
        assert (
            other_logged_client.get(clone_with_added_course.headers["Location"]).status_code == 404
        )
        clone_review = student_client.get(clone_with_added_course.headers["Location"])
        assert clone_review.status_code == 200
        clone_review_body = clone_review.get_data(as_text=True)
        assert "학생 성적 입력 검수" in clone_review_body
        assert "학생 본인 과목" in clone_review_body
        assert "복제 뒤 추가한 합성 과목" in clone_review_body
        forbidden_clone = student_client.get(
            f"/account/consultations/{teacher_consultation.id}/clone"
        )
        assert forbidden_clone.status_code == 404
        edit_data = {
            "csrf_token": csrf,
            "academic_year": "2026",
            "grade": "1",
            "semester": "1",
            "record_source": "VOCATIONAL_TRAINING_RECORD",
            "is_vocational_training_semester": "TRUE",
            "vocational_institution_name": "합성 위탁기관",
            f"course-{own_course.id}-subject_group": "수학",
            f"course-{own_course.id}-subject_name": "학생 수정 과목",
            f"course-{own_course.id}-credits": "3",
            f"course-{own_course.id}-raw_score": "P",
            f"course-{own_course.id}-course_mean": "65.5",
            f"course-{own_course.id}-standard_deviation": "10.5",
            f"course-{own_course.id}-achievement_level": "A",
            f"course-{own_course.id}-enrollment_count": "99",
            f"course-{own_course.id}-rank_grade": "4",
        }
        edited = student_client.post(f"/account/records/{own_record.id}/edit", data=edit_data)
        assert edited.status_code == 302
        invalid_zero = dict(edit_data)
        invalid_zero[f"course-{own_course.id}-credits"] = "0"
        invalid = student_client.post(f"/account/records/{own_record.id}/edit", data=invalid_zero)
        assert invalid.status_code == 400
        assert "0 초과 999.99 이하" in invalid.get_data(as_text=True)
        forbidden = student_client.post(
            f"/account/records/{other_record.id}/edit",
            data={"csrf_token": csrf},
        )
        assert forbidden.status_code == 400

        teacher_client = app.test_client()
        teacher_csrf = _login_as(teacher_client, teacher)
        teacher_page = teacher_client.get("/account/records")
        teacher_body = teacher_page.get_data(as_text=True)
        assert "teacher-managed-synthetic-student" in teacher_body
        assert "other-teacher-managed-student" not in teacher_body
        teacher_print = teacher_client.get(
            f"/account/consultations/{teacher_consultation.id}/print/teacher"
        )
        assert teacher_print.status_code == 200
        assert "교사용 계산 근거" in teacher_print.get_data(as_text=True)
        assert "동양미래대학교" in teacher_print.get_data(as_text=True)
        forbidden_print = teacher_client.get(
            f"/account/consultations/{other_consultation.id}/print/teacher"
        )
        assert forbidden_print.status_code == 404
        note = teacher_client.post(
            f"/account/consultations/{teacher_consultation.id}/note",
            data={"csrf_token": teacher_csrf, "counselor_note": "합성 상담 메모"},
        )
        assert note.status_code == 302
        forbidden_note = teacher_client.post(
            f"/account/consultations/{other_consultation.id}/note",
            data={"csrf_token": teacher_csrf, "counselor_note": "권한 밖 메모"},
        )
        assert forbidden_note.status_code == 404

        with Session(postgres_engine) as database_session:
            stored_course = database_session.get(StudentCourseRecord, own_course.id)
            stored_consultation = database_session.get(SavedConsultation, teacher_consultation.id)
            assert stored_course is not None
            assert (stored_course.subject_name, stored_course.rank_grade) == (
                "학생 수정 과목",
                Decimal("4"),
            )
            assert stored_course.subject_group == "수학"
            assert stored_course.raw_score is None
            assert stored_course.raw_score_label == "P"
            assert stored_course.course_mean == Decimal("65.5")
            assert stored_course.standard_deviation == Decimal("10.5")
            assert stored_course.achievement_level == "A"
            assert stored_course.enrollment_count == 99
            stored_record = database_session.get(StudentAcademicRecord, own_record.id)
            assert stored_record is not None
            assert stored_record.record_source == "VOCATIONAL_TRAINING_RECORD"
            assert stored_record.is_vocational_training_semester
            assert stored_record.vocational_institution_name == "합성 위탁기관"
            assert stored_consultation is not None
            assert stored_consultation.counselor_note == "합성 상담 메모"
    finally:
        if created_user_ids:
            with postgres_engine.begin() as connection:
                connection.execute(
                    delete(StudentCourseRecord).where(
                        StudentCourseRecord.academic_record_id.in_(record_ids)
                    )
                )
                connection.execute(
                    delete(StudentAcademicRecord).where(StudentAcademicRecord.id.in_(record_ids))
                )
                connection.execute(
                    delete(SavedConsultation).where(
                        (SavedConsultation.owner_user_account_id.in_(created_user_ids))
                        | (SavedConsultation.managed_by_user_account_id.in_(created_user_ids))
                    )
                )
                connection.execute(
                    delete(UserAccountAuditEvent).where(
                        (UserAccountAuditEvent.target_user_id.in_(created_user_ids))
                        | (UserAccountAuditEvent.actor_user_id.in_(created_user_ids))
                    )
                )
                connection.execute(
                    delete(UserAccount).where(UserAccount.id.in_(created_user_ids[:-1]))
                )
                connection.execute(
                    delete(UserAccount).where(UserAccount.id == created_user_ids[-1])
                )
