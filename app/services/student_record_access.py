from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import (
    SavedConsultation,
    StudentAcademicRecord,
    StudentCourseRecord,
    UserAccount,
)
from app.services.classroom_links import (
    linked_classroom_student_references,
    linked_student_account_ids,
    linked_teacher_user_ids,
)
from app.services.membership import has_teacher_capability


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
REFERENCE_INPUT_TERMS = (
    (2025, "1", "1"),
    (2025, "1", "2"),
    (2026, "2", "1"),
    (2026, "2", "2"),
    (2027, "3", "1"),
    (2027, "3", "2"),
)
REFERENCE_INPUT_ROWS_PER_TERM = 10


def can_access_academic_record(user: UserAccount, record: StudentAcademicRecord) -> bool:
    """자료를 수정·삭제할 수 있는 직접 소유자 또는 관리자 여부."""
    if user.status != "ACTIVE":
        return False
    if user.role == "ADMIN":
        return True
    if user.role == "STUDENT":
        return record.owner_user_account_id == user.id
    if user.role == "TEACHER":
        return record.managed_by_user_account_id == user.id
    return False


def can_read_academic_record(
    session: Session, *, user: UserAccount, record: StudentAcademicRecord
) -> bool:
    if can_access_academic_record(user, record):
        return True
    if user.status != "ACTIVE":
        return False
    if user.role == "STUDENT":
        return record.student_id in linked_classroom_student_references(
            session, student_user_id=user.id
        )
    if user.role == "TEACHER" and record.owner_user_account_id:
        return record.owner_user_account_id in linked_student_account_ids(
            session, teacher_user_id=user.id
        )
    return False


def visible_academic_records(
    session: Session, *, user: UserAccount
) -> tuple[StudentAcademicRecord, ...]:
    if user.status != "ACTIVE":
        raise StudentRecordAccessError("활성 계정만 저장 성적을 조회할 수 있습니다.")
    statement = select(StudentAcademicRecord)
    if user.role == "STUDENT":
        shared_references = linked_classroom_student_references(session, student_user_id=user.id)
        statement = statement.where(
            or_(
                StudentAcademicRecord.owner_user_account_id == user.id,
                StudentAcademicRecord.student_id.in_(shared_references),
            )
        )
    elif user.role == "TEACHER":
        linked_user_ids = linked_student_account_ids(session, teacher_user_id=user.id)
        statement = statement.where(
            or_(
                StudentAcademicRecord.managed_by_user_account_id == user.id,
                StudentAcademicRecord.owner_user_account_id.in_(linked_user_ids),
            )
        )
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
    """상담을 수정·삭제할 수 있는 직접 소유자 또는 관리자 여부."""
    if user.status != "ACTIVE":
        return False
    if user.role == "ADMIN":
        return True
    if user.role == "STUDENT":
        return consultation.owner_user_account_id == user.id
    if user.role == "TEACHER":
        return consultation.managed_by_user_account_id == user.id
    return False


def can_read_saved_consultation(
    session: Session, *, user: UserAccount, consultation: SavedConsultation
) -> bool:
    if can_access_saved_consultation(user, consultation):
        return True
    if user.status != "ACTIVE":
        return False
    if user.role == "STUDENT":
        return consultation.student_reference in linked_classroom_student_references(
            session, student_user_id=user.id
        ) or (
            consultation.student_reference == f"account:{user.id}"
            and consultation.managed_by_user_account_id
            in linked_teacher_user_ids(session, student_user_id=user.id)
        )
    if user.role == "TEACHER" and consultation.owner_user_account_id:
        return consultation.owner_user_account_id in linked_student_account_ids(
            session, teacher_user_id=user.id
        )
    return False


def visible_saved_consultations(
    session: Session, *, user: UserAccount
) -> tuple[SavedConsultation, ...]:
    if user.status != "ACTIVE":
        raise StudentRecordAccessError("활성 계정만 상담 이력을 조회할 수 있습니다.")
    statement = select(SavedConsultation)
    if user.role == "STUDENT":
        shared_references = linked_classroom_student_references(session, student_user_id=user.id)
        linked_teacher_ids = linked_teacher_user_ids(session, student_user_id=user.id)
        statement = statement.where(
            or_(
                SavedConsultation.owner_user_account_id == user.id,
                SavedConsultation.student_reference.in_(shared_references),
                and_(
                    SavedConsultation.student_reference == f"account:{user.id}",
                    SavedConsultation.managed_by_user_account_id.in_(linked_teacher_ids),
                ),
            )
        )
    elif user.role == "TEACHER":
        linked_user_ids = linked_student_account_ids(session, teacher_user_id=user.id)
        statement = statement.where(
            or_(
                SavedConsultation.managed_by_user_account_id == user.id,
                SavedConsultation.owner_user_account_id.in_(linked_user_ids),
            )
        )
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
    if consultation is None or not can_read_saved_consultation(
        session, user=user, consultation=consultation
    ):
        raise StudentRecordAccessError("상담 이력을 찾을 수 없습니다.")
    return consultation


def saved_consultation_input_rows(
    session: Session, *, user: UserAccount, consultation_id: str
) -> tuple[dict[str, str], ...]:
    consultation = session.get(SavedConsultation, consultation_id)
    if consultation is None or not can_access_saved_consultation(user, consultation):
        # 공유 자료는 읽기 전용이며 상대방 입력으로 복제하지 않는다.
        raise StudentRecordAccessError("상담 이력을 찾을 수 없습니다.")
    records = tuple(
        session.scalars(
            select(StudentAcademicRecord)
            .where(StudentAcademicRecord.student_id == consultation.student_reference)
            .order_by(
                StudentAcademicRecord.academic_year,
                StudentAcademicRecord.grade,
                StudentAcademicRecord.semester,
                StudentAcademicRecord.id,
            )
        )
    )
    rows: list[dict[str, str]] = []
    for record in records:
        courses = tuple(
            session.scalars(
                select(StudentCourseRecord)
                .where(StudentCourseRecord.academic_record_id == record.id)
                .order_by(StudentCourseRecord.id)
            )
        )
        for course in courses:
            rows.append(
                {
                    "academic_year": str(record.academic_year),
                    "grade": str(record.grade),
                    "semester": str(record.semester),
                    "subject_group": course.subject_group or "",
                    "subject_name": course.subject_name,
                    "credits": _display_optional(course.credits),
                    "raw_score": course.raw_score_label or _display_optional(course.raw_score),
                    "course_mean": _display_optional(course.course_mean),
                    "standard_deviation": _display_optional(course.standard_deviation),
                    "achievement_level": course.achievement_level or "",
                    "enrollment_count": _display_optional(course.enrollment_count),
                    "rank_grade": _display_optional(course.rank_grade),
                    "record_source": record.record_source,
                    "is_vocational_training_semester": (
                        "TRUE" if record.is_vocational_training_semester else "FALSE"
                    ),
                }
            )
    if not rows:
        raise StudentRecordAccessError("복제할 저장 성적을 찾을 수 없습니다.")
    reference_keys = {(grade, semester) for _, grade, semester in REFERENCE_INPUT_TERMS}
    if any((row["grade"], row["semester"]) not in reference_keys for row in rows):
        raise StudentRecordAccessError("기준 입력표에 없는 학기 성적은 복제할 수 없습니다.")
    padded_rows: list[dict[str, str]] = []
    for academic_year, grade, semester in REFERENCE_INPUT_TERMS:
        term_rows = [row for row in rows if row["grade"] == grade and row["semester"] == semester]
        if len(term_rows) > REFERENCE_INPUT_ROWS_PER_TERM:
            raise StudentRecordAccessError("상담 복제는 학기당 10과목까지 지원합니다.")
        padded_rows.extend(term_rows)
        padded_rows.extend(
            {
                "academic_year": str(academic_year),
                "grade": grade,
                "semester": semester,
                "subject_group": "",
                "subject_name": "",
                "credits": "",
                "raw_score": "",
                "course_mean": "",
                "standard_deviation": "",
                "achievement_level": "",
                "enrollment_count": "",
                "rank_grade": "",
                "record_source": "",
                "is_vocational_training_semester": "",
            }
            for _ in range(REFERENCE_INPUT_ROWS_PER_TERM - len(term_rows))
        )
    return tuple(padded_rows)


def _display_optional(value: object | None) -> str:
    return "" if value is None else str(value)


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
        or not has_teacher_capability(user)
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
    "can_read_academic_record",
    "can_read_saved_consultation",
    "delete_academic_record",
    "delete_saved_consultation",
    "get_saved_consultation",
    "saved_consultation_input_rows",
    "update_academic_record_courses",
    "update_consultation_note",
    "visible_academic_records",
    "visible_saved_consultations",
]
