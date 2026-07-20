from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models import (
    ClassroomLinkAuditEvent,
    ClassroomStudent,
    StudentAcademicRecord,
    StudentCourseRecord,
    TeacherClassroom,
    UserAccount,
)
from app.services.membership import DEMO_ACTOR_REF, has_teacher_capability


class ClassroomLinkError(ValueError):
    pass


CLASSROOM_LINK_CODE_TTL = timedelta(hours=24)


@dataclass(frozen=True)
class IssuedClassroomStudent:
    student: ClassroomStudent
    connection_code: str


def classroom_student_reference(classroom_student_id: str) -> str:
    return f"classroom-student:{classroom_student_id}"


def _require_teacher(user: UserAccount) -> None:
    if not has_teacher_capability(user):
        raise ClassroomLinkError("활성 교사 또는 주 관리자 계정만 학급을 관리할 수 있습니다.")


def _teacher_account_condition() -> ColumnElement[bool]:
    return or_(
        UserAccount.role == "TEACHER",
        and_(
            UserAccount.role == "ADMIN",
            UserAccount.actor_ref != DEMO_ACTOR_REF,
            ~UserAccount.actor_ref.like("demo:role:%"),
        ),
    )


def _require_student(user: UserAccount) -> None:
    if user.status != "ACTIVE" or user.role != "STUDENT":
        raise ClassroomLinkError("활성 학생 계정만 교사 학급에 연결할 수 있습니다.")


def _text(raw: str, *, label: str, maximum: int) -> str:
    value = raw.strip()
    if not value or len(value) > maximum:
        raise ClassroomLinkError(f"{label}은 1~{maximum}자로 입력하세요.")
    return value


def _anonymous_student_code(raw: str) -> str:
    value = _text(raw, label="비식별 학생 코드", maximum=40)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,39}", value) is None:
        raise ClassroomLinkError("비식별 학생 코드는 영문·숫자·하이픈·밑줄만 사용하세요.")
    return value


def _integer(raw: str, *, label: str, minimum: int, maximum: int) -> int:
    try:
        value = int(raw.strip())
    except ValueError as error:
        raise ClassroomLinkError(f"{label}은 정수로 입력하세요.") from error
    if not minimum <= value <= maximum:
        raise ClassroomLinkError(f"{label}은 {minimum} 이상 {maximum} 이하로 입력하세요.")
    return value


def _optional_decimal(
    raw: str, *, label: str, minimum: Decimal, maximum: Decimal, positive: bool = False
) -> Decimal | None:
    if not raw.strip():
        return None
    try:
        value = Decimal(raw.strip())
    except InvalidOperation as error:
        raise ClassroomLinkError(f"{label}은 숫자로 입력하세요.") from error
    minimum_valid = value > minimum if positive else value >= minimum
    if not value.is_finite() or not minimum_valid or value > maximum:
        comparison = "초과" if positive else "이상"
        raise ClassroomLinkError(f"{label}은 {minimum} {comparison} {maximum} 이하로 입력하세요.")
    return value


def _optional_integer(raw: str, *, label: str, minimum: int, maximum: int) -> int | None:
    if not raw.strip():
        return None
    return _integer(raw, label=label, minimum=minimum, maximum=maximum)


def _raw_score(raw: str) -> tuple[Decimal | None, str | None]:
    value = raw.strip().upper()
    if not value:
        return None, None
    if value == "P":
        return None, "P"
    return (
        _optional_decimal(value, label="원점수", minimum=Decimal("0"), maximum=Decimal("100")),
        None,
    )


def _digest_connection_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _issue_connection_code(student: ClassroomStudent, *, issued_at: datetime) -> str:
    code = secrets.token_urlsafe(18)
    student.link_code_digest = _digest_connection_code(code)
    student.link_code_hint = code[-4:]
    student.link_code_expires_at = issued_at + CLASSROOM_LINK_CODE_TTL
    student.linked_user_account_id = None
    student.linked_at = None
    return code


def _clear_connection_code(student: ClassroomStudent) -> None:
    student.link_code_digest = None
    student.link_code_hint = None
    student.link_code_expires_at = None
    student.linked_user_account_id = None
    student.linked_at = None


def _audit(
    session: Session,
    *,
    student: ClassroomStudent,
    actor: UserAccount,
    event_type: str,
    occurred_at: datetime,
    details: dict[str, str] | None = None,
) -> None:
    session.add(
        ClassroomLinkAuditEvent(
            classroom_student_id=student.id,
            actor_user_account_id=actor.id,
            event_type=event_type,
            occurred_at=occurred_at,
            details=details or {},
        )
    )


def create_classroom(
    session: Session, *, user: UserAccount, values: Mapping[str, str]
) -> TeacherClassroom:
    _require_teacher(user)
    classroom = TeacherClassroom(
        teacher_user_account_id=user.id,
        academic_year=_integer(
            values.get("academic_year", ""),
            label="학년도",
            minimum=2000,
            maximum=2100,
        ),
        department_name=_text(values.get("department_name", ""), label="학과", maximum=120),
        class_name=_text(values.get("class_name", ""), label="학급", maximum=80),
    )
    session.add(classroom)
    session.flush()
    return classroom


def list_teacher_classrooms(session: Session, *, user: UserAccount) -> tuple[TeacherClassroom, ...]:
    _require_teacher(user)
    return tuple(
        session.scalars(
            select(TeacherClassroom)
            .where(TeacherClassroom.teacher_user_account_id == user.id)
            .order_by(
                TeacherClassroom.academic_year.desc(),
                TeacherClassroom.department_name,
                TeacherClassroom.class_name,
                TeacherClassroom.id,
            )
        )
    )


def _owned_classroom(session: Session, *, user: UserAccount, classroom_id: str) -> TeacherClassroom:
    _require_teacher(user)
    classroom = session.scalar(
        select(TeacherClassroom).where(
            TeacherClassroom.id == classroom_id,
            TeacherClassroom.teacher_user_account_id == user.id,
        )
    )
    if classroom is None:
        raise ClassroomLinkError("학급을 찾을 수 없습니다.")
    return classroom


def list_classroom_students(
    session: Session, *, user: UserAccount, classroom_id: str
) -> tuple[ClassroomStudent, ...]:
    _owned_classroom(session, user=user, classroom_id=classroom_id)
    return tuple(
        session.scalars(
            select(ClassroomStudent)
            .where(ClassroomStudent.classroom_id == classroom_id)
            .order_by(ClassroomStudent.anonymous_code, ClassroomStudent.id)
        )
    )


def _owned_classroom_student(
    session: Session, *, user: UserAccount, classroom_student_id: str, for_update: bool = False
) -> ClassroomStudent:
    _require_teacher(user)
    statement = (
        select(ClassroomStudent)
        .join(TeacherClassroom, TeacherClassroom.id == ClassroomStudent.classroom_id)
        .where(
            ClassroomStudent.id == classroom_student_id,
            TeacherClassroom.teacher_user_account_id == user.id,
        )
    )
    if for_update:
        statement = statement.with_for_update()
    student = session.scalar(statement)
    if student is None:
        raise ClassroomLinkError("학생 항목을 찾을 수 없습니다.")
    return student


def add_classroom_student(
    session: Session,
    *,
    user: UserAccount,
    classroom_id: str,
    anonymous_code: str,
    occurred_at: datetime | None = None,
) -> IssuedClassroomStudent:
    _owned_classroom(session, user=user, classroom_id=classroom_id)
    issued_at = occurred_at or datetime.now(UTC)
    student = ClassroomStudent(
        classroom_id=classroom_id,
        anonymous_code=_anonymous_student_code(anonymous_code),
        link_code_digest="0" * 64,
        link_code_hint="0000",
        link_code_expires_at=issued_at,
    )
    code = _issue_connection_code(student, issued_at=issued_at)
    session.add(student)
    session.flush()
    _audit(
        session,
        student=student,
        actor=user,
        event_type="ROSTER_STUDENT_CREATED",
        occurred_at=issued_at,
    )
    return IssuedClassroomStudent(student, code)


def rotate_connection_code(
    session: Session,
    *,
    user: UserAccount,
    classroom_student_id: str,
    occurred_at: datetime | None = None,
) -> IssuedClassroomStudent:
    student = _owned_classroom_student(
        session, user=user, classroom_student_id=classroom_student_id, for_update=True
    )
    if student.linked_user_account_id is not None:
        raise ClassroomLinkError("이미 연결된 학생의 코드는 재발급할 수 없습니다.")
    issued_at = occurred_at or datetime.now(UTC)
    code = _issue_connection_code(student, issued_at=issued_at)
    _audit(
        session,
        student=student,
        actor=user,
        event_type="LINK_CODE_ROTATED",
        occurred_at=issued_at,
    )
    return IssuedClassroomStudent(student, code)


def connect_student_account(
    session: Session,
    *,
    user: UserAccount,
    connection_code: str,
    consent_confirmed: bool = False,
    occurred_at: datetime | None = None,
) -> ClassroomStudent:
    _require_student(user)
    if not consent_confirmed:
        raise ClassroomLinkError("성적·상담자료 공유 범위에 동의해야 연결할 수 있습니다.")
    code = connection_code.strip()
    if len(code) < 20 or len(code) > 64:
        raise ClassroomLinkError("연결 코드를 확인하세요.")
    linked_at = occurred_at or datetime.now(UTC)
    student = session.scalar(
        select(ClassroomStudent)
        .join(TeacherClassroom, TeacherClassroom.id == ClassroomStudent.classroom_id)
        .join(UserAccount, UserAccount.id == TeacherClassroom.teacher_user_account_id)
        .where(ClassroomStudent.link_code_digest == _digest_connection_code(code))
        .where(
            ClassroomStudent.link_code_expires_at > linked_at,
            UserAccount.status == "ACTIVE",
            _teacher_account_condition(),
        )
        .with_for_update()
    )
    if student is None or student.linked_user_account_id is not None:
        raise ClassroomLinkError("연결 코드를 확인하세요.")
    already_linked = session.scalar(
        select(ClassroomStudent.id).where(
            ClassroomStudent.classroom_id == student.classroom_id,
            ClassroomStudent.linked_user_account_id == user.id,
        )
    )
    if already_linked is not None:
        raise ClassroomLinkError("이미 이 학급에 연결되어 있습니다.")
    student.linked_user_account_id = user.id
    student.linked_at = linked_at
    student.link_code_digest = None
    student.link_code_hint = None
    student.link_code_expires_at = None
    _audit(
        session,
        student=student,
        actor=user,
        event_type="STUDENT_LINKED",
        occurred_at=linked_at,
        details={"scope": "ACCOUNT_RECORDS_AND_CONSULTATIONS_WHILE_LINKED"},
    )
    return student


def disconnect_student_account(
    session: Session,
    *,
    user: UserAccount,
    classroom_student_id: str,
    occurred_at: datetime | None = None,
) -> ClassroomStudent:
    student = session.scalar(
        select(ClassroomStudent)
        .where(ClassroomStudent.id == classroom_student_id)
        .with_for_update()
    )
    if student is None or student.linked_user_account_id is None:
        raise ClassroomLinkError("연결된 학생을 찾을 수 없습니다.")
    classroom = session.get(TeacherClassroom, student.classroom_id)
    permitted = user.status == "ACTIVE" and (
        (
            has_teacher_capability(user)
            and classroom is not None
            and classroom.teacher_user_account_id == user.id
        )
        or (user.role == "STUDENT" and student.linked_user_account_id == user.id)
    )
    if not permitted:
        raise ClassroomLinkError("연결된 학생을 찾을 수 없습니다.")
    _clear_connection_code(student)
    _audit(
        session,
        student=student,
        actor=user,
        event_type="STUDENT_UNLINKED",
        occurred_at=occurred_at or datetime.now(UTC),
    )
    return student


def linked_classrooms_for_student(
    session: Session, *, user: UserAccount
) -> tuple[tuple[ClassroomStudent, TeacherClassroom], ...]:
    _require_student(user)
    rows = session.execute(
        select(ClassroomStudent, TeacherClassroom)
        .join(TeacherClassroom, TeacherClassroom.id == ClassroomStudent.classroom_id)
        .join(UserAccount, UserAccount.id == TeacherClassroom.teacher_user_account_id)
        .where(
            ClassroomStudent.linked_user_account_id == user.id,
            UserAccount.status == "ACTIVE",
            _teacher_account_condition(),
        )
        .order_by(
            TeacherClassroom.academic_year.desc(),
            TeacherClassroom.department_name,
            TeacherClassroom.class_name,
        )
    )
    return tuple((student, classroom) for student, classroom in rows)


def linked_student_account_ids(session: Session, *, teacher_user_id: str) -> tuple[str, ...]:
    return tuple(
        session.scalars(
            select(ClassroomStudent.linked_user_account_id)
            .join(TeacherClassroom, TeacherClassroom.id == ClassroomStudent.classroom_id)
            .join(UserAccount, UserAccount.id == ClassroomStudent.linked_user_account_id)
            .where(
                TeacherClassroom.teacher_user_account_id == teacher_user_id,
                ClassroomStudent.linked_user_account_id.is_not(None),
                UserAccount.status == "ACTIVE",
                UserAccount.role == "STUDENT",
            )
            .order_by(ClassroomStudent.linked_user_account_id)
        )
    )


def linked_teacher_user_ids(session: Session, *, student_user_id: str) -> tuple[str, ...]:
    return tuple(
        session.scalars(
            select(TeacherClassroom.teacher_user_account_id)
            .join(ClassroomStudent, ClassroomStudent.classroom_id == TeacherClassroom.id)
            .join(UserAccount, UserAccount.id == TeacherClassroom.teacher_user_account_id)
            .where(
                ClassroomStudent.linked_user_account_id == student_user_id,
                UserAccount.status == "ACTIVE",
                _teacher_account_condition(),
            )
            .order_by(TeacherClassroom.teacher_user_account_id)
        )
    )


def linked_classroom_student_references(
    session: Session, *, student_user_id: str
) -> tuple[str, ...]:
    ids = tuple(
        session.scalars(
            select(ClassroomStudent.id)
            .join(TeacherClassroom, TeacherClassroom.id == ClassroomStudent.classroom_id)
            .join(UserAccount, UserAccount.id == TeacherClassroom.teacher_user_account_id)
            .where(ClassroomStudent.linked_user_account_id == student_user_id)
            .where(UserAccount.status == "ACTIVE", _teacher_account_condition())
            .order_by(ClassroomStudent.id)
        )
    )
    return tuple(classroom_student_reference(item) for item in ids)


def teacher_owned_student_references(session: Session, *, teacher_user_id: str) -> tuple[str, ...]:
    ids = tuple(
        session.scalars(
            select(ClassroomStudent.id)
            .join(TeacherClassroom, TeacherClassroom.id == ClassroomStudent.classroom_id)
            .where(TeacherClassroom.teacher_user_account_id == teacher_user_id)
            .order_by(ClassroomStudent.id)
        )
    )
    return tuple(classroom_student_reference(item) for item in ids)


def add_classroom_course(
    session: Session,
    *,
    user: UserAccount,
    classroom_student_id: str,
    values: Mapping[str, str],
) -> StudentCourseRecord:
    student = _owned_classroom_student(
        session, user=user, classroom_student_id=classroom_student_id, for_update=True
    )
    academic_year = _integer(
        values.get("academic_year", ""), label="학년도", minimum=2000, maximum=2100
    )
    grade = _integer(values.get("grade", ""), label="학년", minimum=1, maximum=3)
    semester = _integer(values.get("semester", ""), label="학기", minimum=1, maximum=2)
    record_source = values.get("record_source", "").strip()
    if record_source not in {
        "HOME_SCHOOL_RECORD",
        "VOCATIONAL_TRAINING_RECORD",
        "GED_RECORD",
        "MANUAL_INPUT",
    }:
        raise ClassroomLinkError("성적 출처를 확인하세요.")
    student_reference = classroom_student_reference(student.id)
    record = session.scalar(
        select(StudentAcademicRecord)
        .where(
            StudentAcademicRecord.student_id == student_reference,
            StudentAcademicRecord.academic_year == academic_year,
            StudentAcademicRecord.grade == grade,
            StudentAcademicRecord.semester == semester,
            StudentAcademicRecord.record_source == record_source,
        )
        .with_for_update()
    )
    if record is None:
        record = StudentAcademicRecord(
            student_id=student_reference,
            owner_user_account_id=None,
            managed_by_user_account_id=user.id,
            academic_year=academic_year,
            grade=grade,
            semester=semester,
            record_source=record_source,
            is_vocational_training_semester=(
                values.get("is_vocational_training_semester", "").strip().upper() == "TRUE"
            ),
            verification_status="USER_VERIFIED",
        )
        session.add(record)
        session.flush()
    elif record.managed_by_user_account_id != user.id or record.owner_user_account_id is not None:
        raise ClassroomLinkError("다른 소유자의 성적과 충돌하여 추가할 수 없습니다.")

    subject_name = _text(values.get("subject_name", ""), label="과목명", maximum=200)
    subject_group = values.get("subject_group", "").strip()
    if len(subject_group) > 120:
        raise ClassroomLinkError("교과는 120자 이하여야 합니다.")
    achievement_level = values.get("achievement_level", "").strip()
    if len(achievement_level) > 20:
        raise ClassroomLinkError("성취도는 20자 이하여야 합니다.")
    raw_score, raw_score_label = _raw_score(values.get("raw_score", ""))
    course = StudentCourseRecord(
        academic_record_id=record.id,
        subject_group=subject_group or None,
        subject_name=subject_name,
        credits=_optional_decimal(
            values.get("credits", ""),
            label="이수단위",
            minimum=Decimal("0"),
            maximum=Decimal("999.99"),
            positive=True,
        ),
        raw_score=raw_score,
        raw_score_label=raw_score_label,
        course_mean=_optional_decimal(
            values.get("course_mean", ""),
            label="과목평균",
            minimum=Decimal("0"),
            maximum=Decimal("100"),
        ),
        standard_deviation=_optional_decimal(
            values.get("standard_deviation", ""),
            label="표준편차",
            minimum=Decimal("0"),
            maximum=Decimal("100"),
            positive=True,
        ),
        achievement_level=achievement_level or None,
        enrollment_count=_optional_integer(
            values.get("enrollment_count", ""),
            label="수강자수",
            minimum=1,
            maximum=1_000_000,
        ),
        rank_grade=_optional_decimal(
            values.get("rank_grade", ""),
            label="석차등급",
            minimum=Decimal("1"),
            maximum=Decimal("9"),
        ),
        extraction_method="TEACHER_MANUAL",
        user_verified=True,
    )
    session.add(course)
    session.flush()
    return course


def classroom_student_records(
    session: Session, *, user: UserAccount, classroom_student_id: str
) -> tuple[StudentAcademicRecord, ...]:
    student = _owned_classroom_student(
        session, user=user, classroom_student_id=classroom_student_id
    )
    access_filter = StudentAcademicRecord.student_id == classroom_student_reference(student.id)
    if student.linked_user_account_id is not None:
        access_filter = or_(
            access_filter,
            StudentAcademicRecord.owner_user_account_id == student.linked_user_account_id,
        )
    return tuple(
        session.scalars(
            select(StudentAcademicRecord)
            .where(access_filter)
            .order_by(
                StudentAcademicRecord.academic_year,
                StudentAcademicRecord.grade,
                StudentAcademicRecord.semester,
                StudentAcademicRecord.record_source,
            )
        )
    )


__all__ = [
    "ClassroomLinkError",
    "IssuedClassroomStudent",
    "add_classroom_course",
    "add_classroom_student",
    "classroom_student_records",
    "classroom_student_reference",
    "connect_student_account",
    "create_classroom",
    "disconnect_student_account",
    "linked_classroom_student_references",
    "linked_classrooms_for_student",
    "linked_student_account_ids",
    "linked_teacher_user_ids",
    "list_classroom_students",
    "list_teacher_classrooms",
    "rotate_connection_code",
    "teacher_owned_student_references",
]
