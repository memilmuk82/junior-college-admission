from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import Engine, delete, or_, select
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app import create_app
from app.models import (
    ClassroomLinkAuditEvent,
    ClassroomStudent,
    SavedConsultation,
    StudentAcademicRecord,
    StudentCourseRecord,
    TeacherClassroom,
    UserAccount,
    UserAccountAuditEvent,
)
from app.services.classroom_links import (
    ClassroomLinkError,
    add_classroom_course,
    add_classroom_student,
    classroom_student_reference,
    connect_student_account,
    create_classroom,
)
from app.services.membership import bootstrap_admin, change_member_role, change_member_status
from app.services.student_record_access import (
    visible_academic_records,
    visible_saved_consultations,
)
from tests.test_consultation_routes import _cleanup, _form, _seed

ACCOUNT_PREFIX = "phase16-classroom-link-contract-"
PASSWORD_HASH = generate_password_hash("phase16-classroom-link-password")
CSRF_TOKEN = "phase16-classroom-link-csrf"


def _cleanup_phase16_contract_rows(postgres_engine: Engine) -> None:
    with Session(postgres_engine) as database_session:
        account_ids = tuple(
            database_session.scalars(
                select(UserAccount.id).where(UserAccount.login_name.like(f"{ACCOUNT_PREFIX}%"))
            )
        )
        if not account_ids:
            return

        classroom_ids = tuple(
            database_session.scalars(
                select(TeacherClassroom.id).where(
                    TeacherClassroom.teacher_user_account_id.in_(account_ids)
                )
            )
        )
        classroom_student_ids = (
            tuple(
                database_session.scalars(
                    select(ClassroomStudent.id).where(
                        ClassroomStudent.classroom_id.in_(classroom_ids)
                    )
                )
            )
            if classroom_ids
            else ()
        )
        classroom_references = tuple(
            f"classroom-student:{student_id}" for student_id in classroom_student_ids
        )
        record_filter = or_(
            StudentAcademicRecord.owner_user_account_id.in_(account_ids),
            StudentAcademicRecord.managed_by_user_account_id.in_(account_ids),
        )
        if classroom_references:
            record_filter = or_(
                record_filter,
                StudentAcademicRecord.student_id.in_(classroom_references),
            )
        record_ids = tuple(
            database_session.scalars(select(StudentAcademicRecord.id).where(record_filter))
        )
        if record_ids:
            database_session.execute(
                delete(StudentCourseRecord).where(
                    StudentCourseRecord.academic_record_id.in_(record_ids)
                )
            )
            database_session.execute(
                delete(StudentAcademicRecord).where(StudentAcademicRecord.id.in_(record_ids))
            )
        if classroom_student_ids:
            database_session.execute(
                delete(ClassroomLinkAuditEvent).where(
                    ClassroomLinkAuditEvent.classroom_student_id.in_(classroom_student_ids)
                )
            )
            database_session.execute(
                delete(ClassroomStudent).where(ClassroomStudent.id.in_(classroom_student_ids))
            )
        if classroom_ids:
            database_session.execute(
                delete(TeacherClassroom).where(TeacherClassroom.id.in_(classroom_ids))
            )
        database_session.execute(
            delete(UserAccountAuditEvent).where(
                or_(
                    UserAccountAuditEvent.target_user_id.in_(account_ids),
                    UserAccountAuditEvent.actor_user_id.in_(account_ids),
                )
            )
        )
        database_session.execute(
            delete(UserAccount).where(
                UserAccount.id.in_(account_ids),
                UserAccount.role != "ADMIN",
            )
        )
        database_session.execute(delete(UserAccount).where(UserAccount.id.in_(account_ids)))
        database_session.commit()


@pytest.fixture(autouse=True)
def clean_phase16_classroom_link_contract(postgres_engine: Engine) -> Iterator[None]:
    _cleanup_phase16_contract_rows(postgres_engine)
    yield
    _cleanup_phase16_contract_rows(postgres_engine)


@pytest.fixture
def phase16_accounts(postgres_engine: Engine) -> dict[str, UserAccount]:
    with Session(postgres_engine, expire_on_commit=False) as database_session:
        admin = bootstrap_admin(
            database_session,
            login_name=f"{ACCOUNT_PREFIX}admin",
            password_hash=PASSWORD_HASH,
            occurred_at=datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
        )
        accounts: dict[str, UserAccount] = {"admin": admin}
        for index, (key, role) in enumerate(
            (
                ("teacher", "TEACHER"),
                ("student", "STUDENT"),
                ("other_teacher", "TEACHER"),
                ("other_student", "STUDENT"),
            ),
            start=1,
        ):
            login_name = f"{ACCOUNT_PREFIX}{key.replace('_', '-')}"
            account = UserAccount(
                actor_ref=f"user:{login_name}",
                login_name=login_name,
                email=f"{login_name}@example.invalid",
                display_name=f"합성 {key} 계정",
                password_hash=PASSWORD_HASH,
                role=role,
                status="ACTIVE",
                auth_version=1,
                approved_by_user_id=admin.id,
                approved_at=datetime(2026, 7, 20, 9, index, tzinfo=UTC),
            )
            database_session.add(account)
            accounts[key] = account
        database_session.commit()
        for account in accounts.values():
            database_session.refresh(account)
            database_session.expunge(account)
        return accounts


@pytest.fixture
def phase16_app(postgres_engine: Engine, tmp_path) -> Flask:  # type: ignore[no-untyped-def]
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "phase16-classroom-link-test-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "TEMP_UPLOAD_ROOT": str(tmp_path / "uploads"),
            "ALLOW_LEGACY_ADMIN_LOGIN": False,
            "GOOGLE_OIDC_ENABLED": False,
        }
    )


def _client_for(app: Flask, user: UserAccount) -> FlaskClient:
    client = app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = user.id
        browser_session["auth_version"] = user.auth_version
        browser_session["csrf_token"] = CSRF_TOKEN
        browser_session["admin_csrf_token"] = CSRF_TOKEN
    return client


def _connection_code(body: str) -> str:
    match = re.search(r"<code data-connection-code>([^<]+)</code>", body)
    assert match is not None
    return html.unescape(match.group(1)).strip()


def _course_values(subject_name: str) -> dict[str, str]:
    return {
        "csrf_token": CSRF_TOKEN,
        "academic_year": "2026",
        "grade": "3",
        "semester": "1",
        "record_source": "VOCATIONAL_TRAINING_RECORD",
        "is_vocational_training_semester": "TRUE",
        "subject_group": "전문교과",
        "subject_name": subject_name,
        "credits": "3",
        "rank_grade": "2",
        "raw_score": "88",
        "course_mean": "71.5",
        "standard_deviation": "11.2",
        "achievement_level": "A",
        "enrollment_count": "24",
    }


def test_real_admin_can_use_teacher_classroom_routes_and_link_student_account(
    postgres_engine: Engine,
    phase16_app: Flask,
    phase16_accounts: dict[str, UserAccount],
) -> None:
    admin = phase16_accounts["admin"]
    student = phase16_accounts["student"]
    admin_client = _client_for(phase16_app, admin)

    classroom_page = admin_client.get("/teacher/classrooms")
    assert classroom_page.status_code == 200
    assert "학과·학급 추가" in classroom_page.get_data(as_text=True)

    created = admin_client.post(
        "/teacher/classrooms",
        data={
            "csrf_token": CSRF_TOKEN,
            "academic_year": "2027",
            "department_name": "합성 관리자 상담과",
            "class_name": "3-M",
        },
    )
    assert created.status_code == 302

    with Session(postgres_engine, expire_on_commit=False) as database_session:
        classroom = database_session.scalar(
            select(TeacherClassroom).where(
                TeacherClassroom.teacher_user_account_id == admin.id,
                TeacherClassroom.department_name == "합성 관리자 상담과",
                TeacherClassroom.class_name == "3-M",
            )
        )
        assert classroom is not None
        admin_user = database_session.get(UserAccount, admin.id)
        student_user = database_session.get(UserAccount, student.id)
        assert admin_user is not None and student_user is not None
        issued = add_classroom_student(
            database_session,
            user=admin_user,
            classroom_id=classroom.id,
            anonymous_code="C27-ADMIN",
        )
        connect_student_account(
            database_session,
            user=student_user,
            connection_code=issued.connection_code,
            consent_confirmed=True,
        )
        database_session.commit()
        linked_student = database_session.get(ClassroomStudent, issued.student.id)
        assert linked_student is not None
        assert linked_student.linked_user_account_id == student.id


def test_teacher_admin_role_transitions_preserve_classroom_links(
    postgres_engine: Engine,
    phase16_accounts: dict[str, UserAccount],
) -> None:
    with Session(postgres_engine, expire_on_commit=False) as database_session:
        actor = database_session.get(UserAccount, phase16_accounts["admin"].id)
        teacher = database_session.get(UserAccount, phase16_accounts["teacher"].id)
        student = database_session.get(UserAccount, phase16_accounts["student"].id)
        assert actor is not None and teacher is not None and student is not None
        classroom = create_classroom(
            database_session,
            user=teacher,
            values={
                "academic_year": "2027",
                "department_name": "합성 역할 연속과",
                "class_name": "3-R",
            },
        )
        issued = add_classroom_student(
            database_session,
            user=teacher,
            classroom_id=classroom.id,
            anonymous_code="C27-ROLE",
        )
        connect_student_account(
            database_session,
            user=student,
            connection_code=issued.connection_code,
            consent_confirmed=True,
        )
        database_session.commit()

        change_member_role(
            database_session,
            actor=actor,
            target=teacher,
            new_role="ADMIN",
            occurred_at=datetime(2026, 7, 20, 10, 0, tzinfo=UTC),
        )
        database_session.commit()
        promoted_link = database_session.get(ClassroomStudent, issued.student.id)
        assert promoted_link is not None
        assert promoted_link.linked_user_account_id == student.id

        change_member_role(
            database_session,
            actor=actor,
            target=teacher,
            new_role="TEACHER",
            occurred_at=datetime(2026, 7, 20, 10, 1, tzinfo=UTC),
        )
        database_session.commit()
        restored_link = database_session.get(ClassroomStudent, issued.student.id)
        assert restored_link is not None
        assert restored_link.linked_user_account_id == student.id

        change_member_role(
            database_session,
            actor=actor,
            target=teacher,
            new_role="MEMBER",
            occurred_at=datetime(2026, 7, 20, 10, 2, tzinfo=UTC),
        )
        database_session.commit()
        revoked_link = database_session.get(ClassroomStudent, issued.student.id)
        assert revoked_link is not None
        assert revoked_link.linked_user_account_id is None


def test_real_admin_can_save_owned_consultation_and_update_counselor_note(
    postgres_engine: Engine,
    phase16_app: Flask,
    phase16_accounts: dict[str, UserAccount],
) -> None:
    admin = phase16_accounts["admin"]
    track_id = ""
    consultation_id = ""
    try:
        with Session(postgres_engine) as database_session:
            track_id = _seed(database_session)

        admin_client = _client_for(phase16_app, admin)
        form = _form(track_id, CSRF_TOKEN)
        form["consultation_note"] = "합성 주 관리자 최초 상담 메모"
        result_page = admin_client.post("/admin/consultations/new", data=form)
        assert result_page.status_code == 200
        assert "학생 상담자료 저장·공유" in result_page.get_data(as_text=True)

        saved = admin_client.post("/admin/consultations/save", data=form)
        assert saved.status_code == 302
        assert saved.headers["Location"].endswith("/account/records?message=consultation_saved")

        with Session(postgres_engine) as database_session:
            consultation = database_session.scalar(
                select(SavedConsultation).where(
                    SavedConsultation.managed_by_user_account_id == admin.id,
                    SavedConsultation.student_reference == "synthetic-student",
                )
            )
            assert consultation is not None
            consultation_id = consultation.id
            assert consultation.owner_user_account_id is None
            assert consultation.counselor_note == "합성 주 관리자 최초 상담 메모"

        updated = admin_client.post(
            f"/account/consultations/{consultation_id}/note",
            data={
                "csrf_token": CSRF_TOKEN,
                "counselor_note": "합성 주 관리자 갱신 상담 메모",
            },
        )
        assert updated.status_code == 302
        with Session(postgres_engine) as database_session:
            consultation = database_session.get(SavedConsultation, consultation_id)
            assert consultation is not None
            assert consultation.counselor_note == "합성 주 관리자 갱신 상담 메모"
    finally:
        with Session(postgres_engine) as database_session:
            database_session.execute(
                delete(SavedConsultation).where(
                    SavedConsultation.managed_by_user_account_id == admin.id
                )
            )
            database_session.commit()
            if track_id:
                _cleanup(database_session, track_id)


def test_classroom_link_ssr_shares_records_read_only_and_blocks_third_parties(
    postgres_engine: Engine,
    phase16_app: Flask,
    phase16_accounts: dict[str, UserAccount],
) -> None:
    teacher = phase16_accounts["teacher"]
    student = phase16_accounts["student"]
    other_teacher = phase16_accounts["other_teacher"]
    other_student = phase16_accounts["other_student"]
    teacher_client = _client_for(phase16_app, teacher)
    student_client = _client_for(phase16_app, student)
    other_teacher_client = _client_for(phase16_app, other_teacher)
    other_student_client = _client_for(phase16_app, other_student)

    classroom_page = teacher_client.get("/teacher/classrooms")
    classroom_body = classroom_page.get_data(as_text=True)
    assert classroom_page.status_code == 200
    assert "학과·학급과 학생 성적" in classroom_body
    assert "학과·학급 추가" in classroom_body

    created = teacher_client.post(
        "/teacher/classrooms",
        data={
            "csrf_token": CSRF_TOKEN,
            "academic_year": "2027",
            "department_name": "합성 스마트기계과",
            "class_name": "3-A",
        },
    )
    assert created.status_code == 302

    with Session(postgres_engine) as database_session:
        classroom = database_session.scalar(
            select(TeacherClassroom).where(
                TeacherClassroom.teacher_user_account_id == teacher.id,
                TeacherClassroom.department_name == "합성 스마트기계과",
                TeacherClassroom.class_name == "3-A",
            )
        )
        assert classroom is not None
        classroom_id = classroom.id

    roster_response = teacher_client.post(
        f"/teacher/classrooms/{classroom_id}/students",
        data={"csrf_token": CSRF_TOKEN, "anonymous_code": "C27-001"},
    )
    roster_body = roster_response.get_data(as_text=True)
    assert roster_response.status_code == 201
    assert "한 번만 표시" in roster_body
    connection_code = _connection_code(roster_body)
    assert 20 <= len(connection_code) <= 64

    with Session(postgres_engine) as database_session:
        roster_student = database_session.scalar(
            select(ClassroomStudent).where(
                ClassroomStudent.classroom_id == classroom_id,
                ClassroomStudent.anonymous_code == "C27-001",
            )
        )
        assert roster_student is not None
        roster_student_id = roster_student.id
        assert roster_student.linked_user_account_id is None
        assert (
            roster_student.link_code_digest
            == hashlib.sha256(connection_code.encode("utf-8")).hexdigest()
        )
        assert roster_student.link_code_digest != connection_code
        assert roster_student.link_code_hint == connection_code[-4:]
        persisted_link_data = json.dumps(
            {
                "anonymous_code": roster_student.anonymous_code,
                "link_code_digest": roster_student.link_code_digest,
                "link_code_hint": roster_student.link_code_hint,
                "audit_details": [
                    event.details
                    for event in database_session.scalars(
                        select(ClassroomLinkAuditEvent).where(
                            ClassroomLinkAuditEvent.classroom_student_id == roster_student.id
                        )
                    )
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        assert connection_code not in persisted_link_data

    added_course = teacher_client.post(
        f"/teacher/students/{roster_student_id}/courses",
        data=_course_values("합성 교사 입력 과목"),
    )
    assert added_course.status_code == 302

    with Session(postgres_engine) as database_session:
        teacher_record = database_session.scalar(
            select(StudentAcademicRecord).where(
                StudentAcademicRecord.student_id == f"classroom-student:{roster_student_id}"
            )
        )
        assert teacher_record is not None
        assert teacher_record.owner_user_account_id is None
        assert teacher_record.managed_by_user_account_id == teacher.id
        teacher_record_id = teacher_record.id
        teacher_course = database_session.scalar(
            select(StudentCourseRecord).where(
                StudentCourseRecord.academic_record_id == teacher_record.id
            )
        )
        assert teacher_course is not None
        teacher_course_id = teacher_course.id

    before_link = student_client.get("/account/records").get_data(as_text=True)
    assert "합성 교사 입력 과목" not in before_link
    missing_consent = student_client.post(
        "/account/classroom-links",
        data={"csrf_token": CSRF_TOKEN, "connection_code": connection_code},
    )
    assert missing_consent.status_code == 400
    assert "공유 범위에 동의" in missing_consent.get_data(as_text=True)
    linked = student_client.post(
        "/account/classroom-links",
        data={
            "csrf_token": CSRF_TOKEN,
            "connection_code": connection_code,
            "share_consent": "AGREED",
        },
    )
    assert linked.status_code == 302
    assert linked.headers["Location"].endswith("/account/records?message=classroom_connected")

    with Session(postgres_engine) as database_session:
        linked_roster_student = database_session.get(ClassroomStudent, roster_student_id)
        assert linked_roster_student is not None
        assert linked_roster_student.linked_user_account_id == student.id
        assert linked_roster_student.linked_at is not None
        assert linked_roster_student.link_code_digest is None
        assert linked_roster_student.link_code_hint is None

        student_record = StudentAcademicRecord(
            student_id=f"account:{student.id}",
            owner_user_account_id=student.id,
            managed_by_user_account_id=None,
            academic_year=2026,
            grade=2,
            semester=1,
            record_source="HOME_SCHOOL_RECORD",
            is_vocational_training_semester=False,
            verification_status="USER_VERIFIED",
        )
        database_session.add(student_record)
        database_session.flush()
        student_course = StudentCourseRecord(
            academic_record_id=student_record.id,
            subject_group="국어",
            subject_name="합성 학생 소유 과목",
            credits=Decimal("4"),
            rank_grade=Decimal("3"),
            extraction_method="ANONYMOUS_CONFIRMED",
            user_verified=True,
        )
        database_session.add(student_course)
        database_session.commit()
        student_record_id = student_record.id
        student_course_id = student_course.id

    reused = other_student_client.post(
        "/account/classroom-links",
        data={
            "csrf_token": CSRF_TOKEN,
            "connection_code": connection_code,
            "share_consent": "AGREED",
        },
    )
    assert reused.status_code == 400
    assert "연결 코드를 확인하세요" in reused.get_data(as_text=True)

    student_records_page = student_client.get("/account/records")
    student_records_body = student_records_page.get_data(as_text=True)
    assert student_records_page.status_code == 200
    assert "합성 스마트기계과" in student_records_body
    assert "C27-001" in student_records_body
    assert "합성 교사 입력 과목" in student_records_body
    assert "합성 학생 소유 과목" in student_records_body
    assert "읽기 전용 공유" in student_records_body
    assert f'action="/account/records/{teacher_record_id}/edit"' not in student_records_body
    assert f'action="/account/records/{teacher_record_id}/delete"' not in student_records_body
    assert f'action="/account/records/{student_record_id}/edit"' in student_records_body

    teacher_records_page = teacher_client.get("/account/records")
    teacher_records_body = teacher_records_page.get_data(as_text=True)
    assert teacher_records_page.status_code == 200
    assert "합성 교사 입력 과목" in teacher_records_body
    assert "합성 학생 소유 과목" in teacher_records_body
    assert f'action="/account/records/{teacher_record_id}/edit"' in teacher_records_body
    assert f'action="/account/records/{student_record_id}/edit"' not in teacher_records_body
    assert f'action="/account/records/{student_record_id}/delete"' not in teacher_records_body

    assert (
        student_client.post(
            f"/account/records/{teacher_record_id}/edit",
            data={"csrf_token": CSRF_TOKEN},
        ).status_code
        == 400
    )
    assert (
        student_client.post(
            f"/account/records/{teacher_record_id}/delete",
            data={"csrf_token": CSRF_TOKEN},
        ).status_code
        == 404
    )
    assert (
        teacher_client.post(
            f"/account/records/{student_record_id}/edit",
            data={"csrf_token": CSRF_TOKEN},
        ).status_code
        == 400
    )
    assert (
        teacher_client.post(
            f"/account/records/{student_record_id}/delete",
            data={"csrf_token": CSRF_TOKEN},
        ).status_code
        == 404
    )

    other_student_body = other_student_client.get("/account/records").get_data(as_text=True)
    other_teacher_body = other_teacher_client.get("/account/records").get_data(as_text=True)
    other_teacher_classrooms = other_teacher_client.get("/teacher/classrooms").get_data(
        as_text=True
    )
    assert "합성 교사 입력 과목" not in other_student_body
    assert "합성 학생 소유 과목" not in other_student_body
    assert "합성 교사 입력 과목" not in other_teacher_body
    assert "합성 학생 소유 과목" not in other_teacher_body
    assert "합성 스마트기계과" not in other_teacher_classrooms
    assert "C27-001" not in other_teacher_classrooms
    blocked_third_teacher_add = other_teacher_client.post(
        f"/teacher/students/{roster_student_id}/courses",
        data=_course_values("권한 밖 과목"),
    )
    assert blocked_third_teacher_add.status_code == 400

    with Session(postgres_engine) as database_session:
        student_visible_ids = {
            record.id for record in visible_academic_records(database_session, user=student)
        }
        teacher_visible_ids = {
            record.id for record in visible_academic_records(database_session, user=teacher)
        }
        other_student_visible_ids = {
            record.id for record in visible_academic_records(database_session, user=other_student)
        }
        other_teacher_visible_ids = {
            record.id for record in visible_academic_records(database_session, user=other_teacher)
        }
        assert {teacher_record_id, student_record_id} <= student_visible_ids
        assert {teacher_record_id, student_record_id} <= teacher_visible_ids
        assert teacher_record_id not in other_student_visible_ids
        assert student_record_id not in other_student_visible_ids
        assert teacher_record_id not in other_teacher_visible_ids
        assert student_record_id not in other_teacher_visible_ids
        assert database_session.get(StudentCourseRecord, teacher_course_id) is not None
        assert database_session.get(StudentCourseRecord, student_course_id) is not None
        assert (
            database_session.scalar(
                select(StudentCourseRecord.id).where(
                    StudentCourseRecord.subject_name == "권한 밖 과목"
                )
            )
            is None
        )

    disconnected = student_client.post(
        f"/account/classroom-links/{roster_student_id}/disconnect",
        data={"csrf_token": CSRF_TOKEN},
    )
    assert disconnected.status_code == 302
    assert disconnected.headers["Location"].endswith(
        "/account/records?message=classroom_disconnected"
    )

    with Session(postgres_engine) as database_session:
        disconnected_roster_student = database_session.get(ClassroomStudent, roster_student_id)
        assert disconnected_roster_student is not None
        assert disconnected_roster_student.linked_user_account_id is None
        assert disconnected_roster_student.link_code_digest is None
        assert disconnected_roster_student.link_code_hint is None
        assert disconnected_roster_student.link_code_expires_at is None
        assert {
            record.id for record in visible_academic_records(database_session, user=teacher)
        } == {teacher_record_id}
        assert {
            record.id for record in visible_academic_records(database_session, user=student)
        } == {student_record_id}

    old_code_after_disconnect = other_student_client.post(
        "/account/classroom-links",
        data={
            "csrf_token": CSRF_TOKEN,
            "connection_code": connection_code,
            "share_consent": "AGREED",
        },
    )
    assert old_code_after_disconnect.status_code == 400
    assert "연결 코드를 확인하세요" in old_code_after_disconnect.get_data(as_text=True)

    rotated = teacher_client.post(
        f"/teacher/students/{roster_student_id}/link-code",
        data={"csrf_token": CSRF_TOKEN},
    )
    rotated_body = rotated.get_data(as_text=True)
    assert rotated.status_code == 200
    rotated_code = _connection_code(rotated_body)
    assert rotated_code != connection_code

    reconnected = student_client.post(
        "/account/classroom-links",
        data={
            "csrf_token": CSRF_TOKEN,
            "connection_code": rotated_code,
            "share_consent": "AGREED",
        },
    )
    assert reconnected.status_code == 302
    reused_rotated_code = other_student_client.post(
        "/account/classroom-links",
        data={
            "csrf_token": CSRF_TOKEN,
            "connection_code": rotated_code,
            "share_consent": "AGREED",
        },
    )
    assert reused_rotated_code.status_code == 400

    with Session(postgres_engine) as database_session:
        events = tuple(
            database_session.scalars(
                select(ClassroomLinkAuditEvent)
                .where(ClassroomLinkAuditEvent.classroom_student_id == roster_student_id)
                .order_by(ClassroomLinkAuditEvent.occurred_at, ClassroomLinkAuditEvent.id)
            )
        )
        event_types = tuple(event.event_type for event in events)
        assert event_types.count("ROSTER_STUDENT_CREATED") == 1
        assert event_types.count("STUDENT_LINKED") == 2
        assert event_types.count("STUDENT_UNLINKED") == 1
        assert event_types.count("LINK_CODE_ROTATED") == 1
        assert all(event.actor_user_account_id for event in events)
        assert all(
            event.details
            == (
                {"scope": "ACCOUNT_RECORDS_AND_CONSULTATIONS_WHILE_LINKED"}
                if event.event_type == "STUDENT_LINKED"
                else {}
            )
            for event in events
        )


def test_teacher_saved_consultations_are_shared_only_while_student_is_linked(
    postgres_engine: Engine,
    phase16_app: Flask,
    phase16_accounts: dict[str, UserAccount],
) -> None:
    teacher = phase16_accounts["teacher"]
    student = phase16_accounts["student"]
    track_id = ""
    try:
        with Session(postgres_engine, expire_on_commit=False) as database_session:
            track_id = _seed(database_session)
            classroom = create_classroom(
                database_session,
                user=teacher,
                values={
                    "academic_year": "2027",
                    "department_name": "합성 상담과",
                    "class_name": "3-B",
                },
            )
            issued = add_classroom_student(
                database_session,
                user=teacher,
                classroom_id=classroom.id,
                anonymous_code="C27-COUNSEL",
            )
            course_values = _course_values("합성 상담 저장 과목") | {
                "record_source": "HOME_SCHOOL_RECORD",
                "is_vocational_training_semester": "FALSE",
            }
            add_classroom_course(
                database_session,
                user=teacher,
                classroom_student_id=issued.student.id,
                values=course_values,
            )
            connect_student_account(
                database_session,
                user=student,
                connection_code=issued.connection_code,
                consent_confirmed=True,
            )
            student_record = StudentAcademicRecord(
                student_id=f"account:{student.id}",
                owner_user_account_id=student.id,
                academic_year=2026,
                grade=2,
                semester=1,
                record_source="HOME_SCHOOL_RECORD",
                is_vocational_training_semester=False,
                verification_status="USER_VERIFIED",
            )
            database_session.add(student_record)
            database_session.flush()
            database_session.add(
                StudentCourseRecord(
                    academic_record_id=student_record.id,
                    subject_group="국어",
                    subject_name="합성 학생 상담 과목",
                    credits=Decimal("3"),
                    rank_grade=Decimal("2"),
                    extraction_method="ANONYMOUS_CONFIRMED",
                    user_verified=True,
                )
            )
            classroom_student_id = issued.student.id
            classroom_reference = classroom_student_reference(classroom_student_id)
            database_session.commit()

        teacher_client = _client_for(phase16_app, teacher)
        for student_reference in (classroom_reference, f"account:{student.id}"):
            form = _form(track_id, CSRF_TOKEN)
            form["student_id"] = student_reference
            if student_reference == f"account:{student.id}":
                form["graduation_status"] = "GRADUATED"
                form["vocational_training_status"] = "NONE"
                form["vocational_training_semesters"] = ""
            result_page = teacher_client.post("/admin/consultations/new", data=form)
            assert result_page.status_code == 200
            assert "학생 상담자료 저장·공유" in result_page.get_data(as_text=True)
            saved = teacher_client.post("/admin/consultations/save", data=form)
            assert saved.status_code == 302
            assert saved.headers["Location"].endswith("/account/records?message=consultation_saved")

        student_client = _client_for(phase16_app, student)
        student_body = student_client.get("/account/records").get_data(as_text=True)
        assert "합성 상담 전문대" in student_body
        assert "연결 공유 · 읽기 전용" in student_body
        assert "합성 교사용 상담 메모" not in student_body
        with Session(postgres_engine) as database_session:
            teacher_consultations = tuple(
                database_session.scalars(
                    select(SavedConsultation).where(
                        SavedConsultation.managed_by_user_account_id == teacher.id
                    )
                )
            )
            assert {row.student_reference for row in teacher_consultations} == {
                classroom_reference,
                f"account:{student.id}",
            }
            assert {
                row.student_reference: row.student_profile for row in teacher_consultations
            } == {
                classroom_reference: "VOCATIONAL_CURRENT",
                f"account:{student.id}": "GENERAL_GRADUATE",
            }
            assert {
                row.id for row in visible_saved_consultations(database_session, user=student)
            } == {row.id for row in teacher_consultations}

        graduate_consultation = next(
            row for row in teacher_consultations if row.student_reference == f"account:{student.id}"
        )
        graduate_clone = teacher_client.get(
            f"/account/consultations/{graduate_consultation.id}/clone"
        )
        assert graduate_clone.status_code == 200
        graduate_clone_body = graduate_clone.get_data(as_text=True)
        assert 'value="GENERAL_GRADUATE" checked' in graduate_clone_body
        assert (
            'name="rows-40-record_source" type="hidden" '
            'value="HOME_SCHOOL_RECORD"' in graduate_clone_body
        )

        for consultation in teacher_consultations:
            assert f"/account/consultations/{consultation.id}/print/student" in student_body
            assert f"/account/consultations/{consultation.id}/print/teacher" not in student_body
            assert f"/account/consultations/{consultation.id}/clone" not in student_body
            assert (
                student_client.get(
                    f"/account/consultations/{consultation.id}/print/student"
                ).status_code
                == 200
            )
            blocked_teacher_print = student_client.get(
                f"/account/consultations/{consultation.id}/print/teacher"
            )
            assert blocked_teacher_print.status_code == 404
            assert "합성 교사용 상담 메모" not in blocked_teacher_print.get_data(as_text=True)
            blocked_clone = student_client.get(f"/account/consultations/{consultation.id}/clone")
            assert blocked_clone.status_code == 404
            assert 'value="합성 상담 저장 과목"' not in blocked_clone.get_data(as_text=True)

        teacher_body = teacher_client.get("/account/records").get_data(as_text=True)
        assert "합성 교사용 상담 메모" in teacher_body
        assert all(
            f"/account/consultations/{consultation.id}/print/teacher" in teacher_body
            for consultation in teacher_consultations
        )

        disconnected = student_client.post(
            f"/account/classroom-links/{classroom_student_id}/disconnect",
            data={"csrf_token": CSRF_TOKEN},
        )
        assert disconnected.status_code == 302
        with Session(postgres_engine) as database_session:
            assert visible_saved_consultations(database_session, user=student) == ()
            assert (
                len(
                    tuple(
                        database_session.scalars(
                            select(SavedConsultation).where(
                                SavedConsultation.managed_by_user_account_id == teacher.id
                            )
                        )
                    )
                )
                == 2
            )
    finally:
        if track_id:
            with Session(postgres_engine) as database_session:
                _cleanup(database_session, track_id)


def test_link_codes_expire_and_are_revoked_when_teacher_is_suspended(
    postgres_engine: Engine,
    phase16_accounts: dict[str, UserAccount],
) -> None:
    admin = phase16_accounts["admin"]
    teacher = phase16_accounts["teacher"]
    student = phase16_accounts["student"]
    with Session(postgres_engine, expire_on_commit=False) as database_session:
        classroom = create_classroom(
            database_session,
            user=teacher,
            values={
                "academic_year": "2027",
                "department_name": "합성 만료검증과",
                "class_name": "3-C",
            },
        )
        expired = add_classroom_student(
            database_session,
            user=teacher,
            classroom_id=classroom.id,
            anonymous_code="C27-EXPIRED",
            occurred_at=datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
        )
        pending = add_classroom_student(
            database_session,
            user=teacher,
            classroom_id=classroom.id,
            anonymous_code="C27-PENDING",
            occurred_at=datetime(2026, 7, 20, 8, 0, tzinfo=UTC),
        )
        database_session.commit()

        with pytest.raises(ClassroomLinkError, match="연결 코드를 확인하세요"):
            connect_student_account(
                database_session,
                user=student,
                connection_code=expired.connection_code,
                consent_confirmed=True,
                occurred_at=datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
            )

        locked_teacher = database_session.get(UserAccount, teacher.id)
        locked_admin = database_session.get(UserAccount, admin.id)
        assert locked_teacher is not None and locked_admin is not None
        change_member_status(
            database_session,
            actor=locked_admin,
            target=locked_teacher,
            new_status="SUSPENDED",
            occurred_at=datetime(2026, 7, 20, 9, 5, tzinfo=UTC),
        )
        database_session.commit()
        for student_id in (expired.student.id, pending.student.id):
            roster_student = database_session.get(ClassroomStudent, student_id)
            assert roster_student is not None
            assert roster_student.link_code_digest is None
            assert roster_student.link_code_hint is None
            assert roster_student.link_code_expires_at is None

        change_member_status(
            database_session,
            actor=locked_admin,
            target=locked_teacher,
            new_status="ACTIVE",
            occurred_at=datetime(2026, 7, 20, 9, 10, tzinfo=UTC),
        )
        database_session.commit()
        with pytest.raises(ClassroomLinkError, match="연결 코드를 확인하세요"):
            connect_student_account(
                database_session,
                user=student,
                connection_code=pending.connection_code,
                consent_confirmed=True,
                occurred_at=datetime(2026, 7, 20, 9, 11, tzinfo=UTC),
            )
        revoked_events = tuple(
            database_session.scalars(
                select(ClassroomLinkAuditEvent).where(
                    ClassroomLinkAuditEvent.classroom_student_id.in_(
                        (expired.student.id, pending.student.id)
                    ),
                    ClassroomLinkAuditEvent.event_type == "LINK_CODE_REVOKED",
                )
            )
        )
        assert len(revoked_events) == 2
        assert all(
            event.details == {"reason": "ACCOUNT_STATUS_CHANGED"} for event in revoked_events
        )
