"""Create deterministic synthetic accounts for the Phase 16 browser test.

This helper is intentionally limited to a PostgreSQL database supplied through
``DATABASE_URL``.  It never accepts or creates real student data.
"""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime

from sqlalchemy import create_engine, delete, or_, select
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app.models import (
    AiConsultationDraft,
    AiProviderCredential,
    ClassroomStudent,
    ExternalIdentity,
    InstitutionApplicationOutcome,
    SavedConsultation,
    StudentAcademicRecord,
    StudentCourseRecord,
    TeacherClassroom,
    UserAccount,
    UserAccountAuditEvent,
)
from app.services.membership import (
    approve_pending_member,
    bootstrap_admin,
    change_member_role,
    register_local_member,
)

PREFIX = os.environ.get("PHASE16_E2E_PREFIX", "phase16-e2e-")
PASSWORD = os.environ.get("PHASE16_E2E_PASSWORD", "phase16-e2e-password")


def _existing(session: Session, login_name: str) -> UserAccount | None:
    return session.scalar(select(UserAccount).where(UserAccount.login_name == login_name))


def _active_member(
    session: Session,
    *,
    admin: UserAccount,
    login_name: str,
    role: str,
    occurred_at: datetime,
) -> UserAccount:
    existing = _existing(session, login_name)
    if existing is not None:
        if existing.role != role or existing.status != "ACTIVE":
            raise RuntimeError(
                f"합성 E2E 계정 상태가 예상과 다릅니다: {login_name} "
                f"({existing.role}/{existing.status})"
            )
        return existing
    account = register_local_member(
        session,
        login_name=login_name,
        email=f"{login_name}@example.invalid",
        display_name=f"Phase 16 합성 {role} 계정",
        password=PASSWORD,
        requested_role=role,
        occurred_at=occurred_at,
    )
    approve_pending_member(session, actor=admin, target=account, occurred_at=occurred_at)
    return account


def cleanup_synthetic_rows(session: Session) -> None:
    accounts = tuple(
        session.scalars(select(UserAccount).where(UserAccount.login_name.like(f"{PREFIX}%")))
    )
    if not accounts:
        return
    account_ids = tuple(account.id for account in accounts)
    actor_refs = tuple(account.actor_ref for account in accounts)
    classroom_ids = tuple(
        session.scalars(
            select(TeacherClassroom.id).where(
                TeacherClassroom.teacher_user_account_id.in_(account_ids)
            )
        )
    )
    classroom_student_ids = (
        tuple(
            session.scalars(
                select(ClassroomStudent.id).where(ClassroomStudent.classroom_id.in_(classroom_ids))
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
    record_ids = tuple(session.scalars(select(StudentAcademicRecord.id).where(record_filter)))
    if record_ids:
        session.execute(
            delete(StudentCourseRecord).where(
                StudentCourseRecord.academic_record_id.in_(record_ids)
            )
        )
        session.execute(
            delete(StudentAcademicRecord).where(StudentAcademicRecord.id.in_(record_ids))
        )
    session.execute(
        delete(SavedConsultation).where(
            or_(
                SavedConsultation.owner_user_account_id.in_(account_ids),
                SavedConsultation.managed_by_user_account_id.in_(account_ids),
            )
        )
    )
    session.execute(
        delete(InstitutionApplicationOutcome).where(
            InstitutionApplicationOutcome.managed_by_user_account_id.in_(account_ids)
        )
    )
    if classroom_ids:
        session.execute(delete(TeacherClassroom).where(TeacherClassroom.id.in_(classroom_ids)))
    session.execute(
        delete(AiProviderCredential).where(AiProviderCredential.actor_ref.in_(actor_refs))
    )
    session.execute(
        delete(AiConsultationDraft).where(AiConsultationDraft.actor_ref.in_(actor_refs))
    )
    session.execute(
        delete(ExternalIdentity).where(ExternalIdentity.user_account_id.in_(account_ids))
    )
    session.execute(
        delete(UserAccountAuditEvent).where(
            or_(
                UserAccountAuditEvent.target_user_id.in_(account_ids),
                UserAccountAuditEvent.actor_user_id.in_(account_ids),
            )
        )
    )
    admin_ids = tuple(account.id for account in accounts if account.role == "ADMIN")
    session.execute(
        delete(UserAccount).where(
            UserAccount.id.in_(account_ids),
            UserAccount.id.not_in(admin_ids),
        )
    )
    if admin_ids:
        session.execute(delete(UserAccount).where(UserAccount.id.in_(admin_ids)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup-only", action="store_true")
    args = parser.parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url or not database_url.startswith("postgresql+"):
        raise RuntimeError("합성 E2E seed에는 PostgreSQL DATABASE_URL이 필요합니다.")

    engine = create_engine(database_url)
    try:
        with Session(engine) as session:
            cleanup_synthetic_rows(session)
            session.commit()
            if args.cleanup_only:
                return
            now = datetime(2026, 7, 20, 10, 0, tzinfo=UTC)
            admin_login = f"{PREFIX}admin"
            admin = _existing(session, admin_login)
            if admin is None:
                admin = bootstrap_admin(
                    session,
                    login_name=admin_login,
                    password_hash=generate_password_hash(PASSWORD),
                    occurred_at=now,
                )
            elif admin.role != "ADMIN" or admin.status != "ACTIVE":
                raise RuntimeError("합성 E2E 관리자 계정 상태가 예상과 다릅니다.")

            _active_member(
                session,
                admin=admin,
                login_name=f"{PREFIX}teacher",
                role="TEACHER",
                occurred_at=now,
            )
            _active_member(
                session,
                admin=admin,
                login_name=f"{PREFIX}student",
                role="STUDENT",
                occurred_at=now,
            )
            assistant_login = f"{PREFIX}assistant"
            assistant = _existing(session, assistant_login)
            if assistant is None:
                assistant = _active_member(
                    session,
                    admin=admin,
                    login_name=assistant_login,
                    role="TEACHER",
                    occurred_at=now,
                )
                change_member_role(
                    session,
                    actor=admin,
                    target=assistant,
                    new_role="ASSISTANT_ADMIN",
                    occurred_at=now,
                )
            elif assistant.role != "ASSISTANT_ADMIN" or assistant.status != "ACTIVE":
                raise RuntimeError("합성 E2E 보조 관리자 계정 상태가 예상과 다릅니다.")
            session.commit()
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
