from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    SavedConsultation,
    StudentAcademicRecord,
    StudentCourseRecord,
    UserAccount,
)


class StudentRecordAccessError(RuntimeError):
    pass


RECORD_SOURCES = frozenset(
    {
        "HOME_SCHOOL_RECORD",
        "VOCATIONAL_TRAINING_RECORD",
        "GED_RECORD",
        "MANUAL_INPUT",
    }
)


def can_access_academic_record(user: UserAccount, record: StudentAcademicRecord) -> bool:
    if user.status != "ACTIVE":
        return False
    if user.role == "ADMIN":
        return True
    if user.role == "STUDENT":
        return record.owner_user_account_id == user.id
    if user.role == "TEACHER":
        return record.managed_by_user_account_id == user.id
    return False


def visible_academic_records(
    session: Session, *, user: UserAccount
) -> tuple[StudentAcademicRecord, ...]:
    if user.status != "ACTIVE":
        raise StudentRecordAccessError("활성 계정만 저장 성적을 조회할 수 있습니다.")
    statement = select(StudentAcademicRecord)
    if user.role == "STUDENT":
        statement = statement.where(StudentAcademicRecord.owner_user_account_id == user.id)
    elif user.role == "TEACHER":
        statement = statement.where(StudentAcademicRecord.managed_by_user_account_id == user.id)
    elif user.role != "ADMIN":
        raise StudentRecordAccessError("저장 성적 조회 권한이 없습니다.")
    return tuple(
        session.scalars(
            statement.order_by(
                StudentAcademicRecord.student_id,
                StudentAcademicRecord.academic_year,
                StudentAcademicRecord.grade,
                StudentAcademicRecord.semester,
                StudentAcademicRecord.id,
            )
        )
    )


def delete_academic_record(
    session: Session, *, user: UserAccount, record_id: str
) -> StudentAcademicRecord:
    record = session.scalar(
        select(StudentAcademicRecord).where(StudentAcademicRecord.id == record_id).with_for_update()
    )
    if record is None or not can_access_academic_record(user, record):
        # 존재 여부와 소유권 실패를 같은 응답으로 처리한다.
        raise StudentRecordAccessError("저장 성적을 찾을 수 없습니다.")
    session.delete(record)
    return record


def academic_record_courses(
    session: Session, *, records: tuple[StudentAcademicRecord, ...]
) -> dict[str, tuple[StudentCourseRecord, ...]]:
    record_ids = tuple(record.id for record in records)
    if not record_ids:
        return {}
    courses = tuple(
        session.scalars(
            select(StudentCourseRecord)
            .where(StudentCourseRecord.academic_record_id.in_(record_ids))
            .order_by(StudentCourseRecord.academic_record_id, StudentCourseRecord.id)
        )
    )
    return {
        record_id: tuple(course for course in courses if course.academic_record_id == record_id)
        for record_id in record_ids
    }


def update_academic_record_courses(
    session: Session,
    *,
    user: UserAccount,
    record_id: str,
    values: Mapping[str, str],
) -> StudentAcademicRecord:
    record = session.scalar(
        select(StudentAcademicRecord).where(StudentAcademicRecord.id == record_id).with_for_update()
    )
    if record is None or not can_access_academic_record(user, record):
        raise StudentRecordAccessError("저장 성적을 찾을 수 없습니다.")
    record.academic_year = _required_integer(
        values.get("academic_year", ""), label="학년도", minimum=2000, maximum=2100
    )
    record.grade = _required_integer(values.get("grade", ""), label="학년", minimum=1, maximum=3)
    record.semester = _required_integer(
        values.get("semester", ""), label="학기", minimum=1, maximum=2
    )
    record_source = values.get("record_source", "").strip()
    if record_source not in RECORD_SOURCES:
        raise StudentRecordAccessError("성적 출처를 확인하세요.")
    record.record_source = record_source
    vocational_value = values.get("is_vocational_training_semester", "").strip().upper()
    if vocational_value not in {"TRUE", "FALSE"}:
        raise StudentRecordAccessError("위탁학기 여부를 확인하세요.")
    record.is_vocational_training_semester = vocational_value == "TRUE"
    institution_name = values.get("vocational_institution_name", "").strip()
    if len(institution_name) > 200:
        raise StudentRecordAccessError("위탁기관명은 200자 이하여야 합니다.")
    record.vocational_institution_name = institution_name or None
    courses = tuple(
        session.scalars(
            select(StudentCourseRecord).where(StudentCourseRecord.academic_record_id == record.id)
        )
    )
    for course in courses:
        subject_group = values.get(f"course-{course.id}-subject_group", "").strip()
        if len(subject_group) > 120:
            raise StudentRecordAccessError("교과는 120자 이하여야 합니다.")
        subject_name = values.get(f"course-{course.id}-subject_name", "").strip()
        if not subject_name or len(subject_name) > 200:
            raise StudentRecordAccessError("과목명은 1~200자로 입력하세요.")
        course.subject_group = subject_group or None
        course.subject_name = subject_name
        course.credits = _optional_decimal(
            values.get(f"course-{course.id}-credits", ""),
            label="이수단위",
            minimum=Decimal("0"),
            maximum=Decimal("999.99"),
            minimum_inclusive=False,
        )
        raw_score, raw_score_label = _optional_score(
            values.get(f"course-{course.id}-raw_score", "")
        )
        course.raw_score = raw_score
        course.raw_score_label = raw_score_label
        course.course_mean = _optional_decimal(
            values.get(f"course-{course.id}-course_mean", ""),
            label="과목평균",
            minimum=Decimal("0"),
            maximum=Decimal("100"),
        )
        course.standard_deviation = _optional_decimal(
            values.get(f"course-{course.id}-standard_deviation", ""),
            label="표준편차",
            minimum=Decimal("0"),
            maximum=Decimal("100"),
            minimum_inclusive=False,
        )
        achievement_level = values.get(f"course-{course.id}-achievement_level", "").strip()
        if len(achievement_level) > 20:
            raise StudentRecordAccessError("성취도는 20자 이하여야 합니다.")
        course.achievement_level = achievement_level or None
        course.enrollment_count = _optional_integer(
            values.get(f"course-{course.id}-enrollment_count", ""),
            label="수강자수",
            minimum=1,
            maximum=1_000_000,
        )
        course.rank_grade = _optional_decimal(
            values.get(f"course-{course.id}-rank_grade", ""),
            label="석차등급",
            minimum=Decimal("1"),
            maximum=Decimal("9"),
        )
        course.user_verified = True
    record.verification_status = "USER_VERIFIED"
    return record


def _optional_decimal(
    raw: str,
    *,
    label: str,
    minimum: Decimal,
    maximum: Decimal,
    minimum_inclusive: bool = True,
) -> Decimal | None:
    if not raw.strip():
        return None
    try:
        value = Decimal(raw.strip())
    except InvalidOperation as error:
        raise StudentRecordAccessError(f"{label}은 숫자로 입력하세요.") from error
    valid_minimum = value >= minimum if minimum_inclusive else value > minimum
    if not value.is_finite() or not valid_minimum or value > maximum:
        lower_message = "이상" if minimum_inclusive else "초과"
        raise StudentRecordAccessError(
            f"{label}은 {minimum} {lower_message} {maximum} 이하로 입력하세요."
        )
    return value


def _optional_score(raw: str) -> tuple[Decimal | None, str | None]:
    cleaned = raw.strip().upper()
    if not cleaned:
        return None, None
    if cleaned == "P":
        return None, "P"
    return (
        _optional_decimal(
            cleaned,
            label="원점수",
            minimum=Decimal("0"),
            maximum=Decimal("100"),
        ),
        None,
    )


def _optional_integer(raw: str, *, label: str, minimum: int, maximum: int) -> int | None:
    if not raw.strip():
        return None
    try:
        value = Decimal(raw.strip())
    except InvalidOperation as error:
        raise StudentRecordAccessError(f"{label}은 정수로 입력하세요.") from error
    if not value.is_finite() or value != value.to_integral_value():
        raise StudentRecordAccessError(f"{label}은 정수로 입력하세요.")
    integer = int(value)
    if not minimum <= integer <= maximum:
        raise StudentRecordAccessError(f"{label}은 {minimum} 이상 {maximum} 이하로 입력하세요.")
    return integer


def _required_integer(raw: str, *, label: str, minimum: int, maximum: int) -> int:
    value = _optional_integer(raw, label=label, minimum=minimum, maximum=maximum)
    if value is None:
        raise StudentRecordAccessError(f"{label}은 필수입니다.")
    return value


def can_access_saved_consultation(user: UserAccount, consultation: SavedConsultation) -> bool:
    if user.status != "ACTIVE":
        return False
    if user.role == "ADMIN":
        return True
    if user.role == "STUDENT":
        return consultation.owner_user_account_id == user.id
    if user.role == "TEACHER":
        return consultation.managed_by_user_account_id == user.id
    return False


def visible_saved_consultations(
    session: Session, *, user: UserAccount
) -> tuple[SavedConsultation, ...]:
    if user.status != "ACTIVE":
        raise StudentRecordAccessError("활성 계정만 상담 이력을 조회할 수 있습니다.")
    statement = select(SavedConsultation)
    if user.role == "STUDENT":
        statement = statement.where(SavedConsultation.owner_user_account_id == user.id)
    elif user.role == "TEACHER":
        statement = statement.where(SavedConsultation.managed_by_user_account_id == user.id)
    elif user.role != "ADMIN":
        raise StudentRecordAccessError("상담 이력 조회 권한이 없습니다.")
    return tuple(
        session.scalars(
            statement.order_by(SavedConsultation.created_at.desc(), SavedConsultation.id)
        )
    )


def get_saved_consultation(
    session: Session, *, user: UserAccount, consultation_id: str
) -> SavedConsultation:
    consultation = session.get(SavedConsultation, consultation_id)
    if consultation is None or not can_access_saved_consultation(user, consultation):
        raise StudentRecordAccessError("상담 이력을 찾을 수 없습니다.")
    return consultation


def update_consultation_note(
    session: Session,
    *,
    user: UserAccount,
    consultation_id: str,
    counselor_note: str,
) -> SavedConsultation:
    consultation = session.scalar(
        select(SavedConsultation).where(SavedConsultation.id == consultation_id).with_for_update()
    )
    if (
        consultation is None
        or user.status != "ACTIVE"
        or user.role != "TEACHER"
        or consultation.managed_by_user_account_id != user.id
    ):
        raise StudentRecordAccessError("상담 이력을 찾을 수 없습니다.")
    note = counselor_note.strip()
    if len(note) > 2000:
        raise StudentRecordAccessError("상담 메모는 2,000자 이하여야 합니다.")
    consultation.counselor_note = note or None
    return consultation


def delete_saved_consultation(
    session: Session, *, user: UserAccount, consultation_id: str
) -> SavedConsultation:
    consultation = session.scalar(
        select(SavedConsultation).where(SavedConsultation.id == consultation_id).with_for_update()
    )
    if consultation is None or not can_access_saved_consultation(user, consultation):
        raise StudentRecordAccessError("상담 이력을 찾을 수 없습니다.")
    session.delete(consultation)
    return consultation


__all__ = [
    "StudentRecordAccessError",
    "academic_record_courses",
    "can_access_academic_record",
    "can_access_saved_consultation",
    "delete_academic_record",
    "delete_saved_consultation",
    "get_saved_consultation",
    "update_academic_record_courses",
    "update_consultation_note",
    "visible_academic_records",
    "visible_saved_consultations",
]
