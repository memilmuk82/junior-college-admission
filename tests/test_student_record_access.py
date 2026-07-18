from __future__ import annotations

from app.models import StudentAcademicRecord, UserAccount
from app.services.student_record_access import can_access_academic_record


def _user(user_id: str, role: str, *, status: str = "ACTIVE") -> UserAccount:
    return UserAccount(
        id=user_id,
        actor_ref=f"user:{user_id}",
        email=f"{user_id}@local.invalid",
        display_name=user_id,
        role=role,
        status=status,
        auth_version=1,
    )


def _record(*, owner: str | None, teacher: str | None) -> StudentAcademicRecord:
    return StudentAcademicRecord(
        student_id="synthetic-student",
        academic_year=2026,
        grade=1,
        semester=1,
        record_source="MANUAL_INPUT",
        is_vocational_training_semester=False,
        verification_status="USER_VERIFIED",
        owner_user_account_id=owner,
        managed_by_user_account_id=teacher,
    )


def test_student_can_access_only_owned_record() -> None:
    student = _user("student-one", "STUDENT")
    assert can_access_academic_record(student, _record(owner=student.id, teacher=None))
    assert not can_access_academic_record(student, _record(owner="student-two", teacher=None))


def test_teacher_can_access_only_assigned_record() -> None:
    teacher = _user("teacher-one", "TEACHER")
    assert can_access_academic_record(teacher, _record(owner=None, teacher=teacher.id))
    assert not can_access_academic_record(teacher, _record(owner=None, teacher="teacher-two"))


def test_legacy_member_and_inactive_accounts_cannot_access_records() -> None:
    record = _record(owner="account", teacher="account")
    assert not can_access_academic_record(_user("account", "MEMBER"), record)
    assert not can_access_academic_record(_user("account", "STUDENT", status="SUSPENDED"), record)


def test_active_admin_can_access_any_record() -> None:
    assert can_access_academic_record(
        _user("admin-one", "ADMIN"), _record(owner="someone", teacher="teacher")
    )
