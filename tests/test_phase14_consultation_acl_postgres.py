from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app import create_app
from app.models import StudentAcademicRecord, UserAccount, UserAccountAuditEvent
from app.services.membership import bootstrap_admin
from tests.test_account_records_postgres import _active_user, _login_as
from tests.test_consultation_routes import _cleanup, _csrf, _form, _seed


def test_legacy_consultation_route_enforces_student_teacher_record_ownership(
    postgres_engine: Engine,
) -> None:
    track_id = ""
    record_id = ""
    user_ids: tuple[str, ...] = ()
    try:
        with Session(postgres_engine, expire_on_commit=False) as database_session:
            track_id = _seed(database_session)
            admin = bootstrap_admin(
                database_session,
                login_name="phase14-acl-admin",
                password_hash="synthetic-password-hash",
                occurred_at=datetime.now(UTC),
            )
            student = _active_user(admin, "acl-student", "STUDENT")
            teacher = _active_user(admin, "acl-teacher", "TEACHER")
            member = _active_user(admin, "acl-member", "MEMBER")
            database_session.add_all((student, teacher, member))
            database_session.flush()
            record = database_session.scalar(
                select(StudentAcademicRecord).where(
                    StudentAcademicRecord.student_id == "synthetic-student"
                )
            )
            assert record is not None
            record_id = record.id
            record.student_id = f"account:{student.id}"
            record.owner_user_account_id = student.id
            database_session.commit()
            user_ids = (student.id, teacher.id, member.id, admin.id)

        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret",
                "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            }
        )
        student_client = app.test_client()
        _login_as(student_client, student)
        page = student_client.get("/admin/consultations/new")
        student_form = _form(track_id, _csrf(page.get_data(as_text=True)))
        student_form["student_id"] = f"account:{student.id}"
        assert student_client.post("/admin/consultations/new", data=student_form).status_code == 200

        with Session(postgres_engine) as database_session:
            record = database_session.scalar(
                select(StudentAcademicRecord).where(
                    StudentAcademicRecord.student_id == f"account:{student.id}"
                )
            )
            assert record is not None
            record.student_id = "teacher-managed-synthetic"
            record.owner_user_account_id = None
            record.managed_by_user_account_id = teacher.id
            database_session.commit()

        teacher_client = app.test_client()
        _login_as(teacher_client, teacher)
        page = teacher_client.get("/admin/consultations/new")
        teacher_form = _form(track_id, _csrf(page.get_data(as_text=True)))
        teacher_form["student_id"] = "teacher-managed-synthetic"
        assert teacher_client.post("/admin/consultations/new", data=teacher_form).status_code == 200

        member_client = app.test_client()
        _login_as(member_client, member)
        page = member_client.get("/admin/consultations/new")
        member_form = _form(track_id, _csrf(page.get_data(as_text=True)))
        member_form["student_id"] = "teacher-managed-synthetic"
        blocked = member_client.post("/admin/consultations/new", data=member_form)
        assert blocked.status_code == 400
        assert "기존 일반 회원" in blocked.get_data(as_text=True)
    finally:
        if track_id:
            with Session(postgres_engine) as database_session:
                record = database_session.get(StudentAcademicRecord, record_id)
                if record is not None:
                    record.student_id = "synthetic-student"
                    record.owner_user_account_id = None
                    record.managed_by_user_account_id = None
                    database_session.flush()
                _cleanup(database_session, track_id)
                if user_ids:
                    database_session.execute(
                        delete(UserAccountAuditEvent).where(
                            (UserAccountAuditEvent.target_user_id.in_(user_ids))
                            | (UserAccountAuditEvent.actor_user_id.in_(user_ids))
                        )
                    )
                    database_session.execute(
                        delete(UserAccount).where(UserAccount.id.in_(user_ids[:-1]))
                    )
                    database_session.execute(
                        delete(UserAccount).where(UserAccount.id == user_ids[-1])
                    )
                    database_session.commit()
