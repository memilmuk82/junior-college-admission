from __future__ import annotations

from decimal import Decimal

from app.models import (
    ClassroomStudent,
    InstitutionApplicationOutcome,
    StudentAcademicRecord,
    StudentCourseRecord,
    TeacherClassroom,
    UserAccount,
)
from app.services.classroom_links import classroom_student_reference
from app.services.demo_scores import DEMO_SCORE_ROWS
from app.services.institutional_results import InstitutionalOutcomeView, TrackOption


def demo_academic_records(
    user: UserAccount, *, student_id: str | None = None
) -> tuple[
    tuple[StudentAcademicRecord, ...],
    dict[str, tuple[StudentCourseRecord, ...]],
]:
    """DB에 쓰지 않는 역할별 합성 성적 뷰를 만든다."""

    resolved_student_id = student_id or f"demo-score:{user.role.lower()}"
    records: list[StudentAcademicRecord] = []
    courses_by_record: dict[str, tuple[StudentCourseRecord, ...]] = {}
    terms = tuple(
        dict.fromkeys((row.academic_year, row.grade, row.semester) for row in DEMO_SCORE_ROWS)
    )
    for term_index, (academic_year, grade, semester) in enumerate(terms, start=1):
        record_id = f"demo-record-{user.role.lower()}-{term_index}"
        is_vocational_term = grade == 3 and semester == 1
        record = StudentAcademicRecord(
            id=record_id,
            student_id=resolved_student_id,
            owner_user_account_id=user.id if user.role == "STUDENT" else None,
            managed_by_user_account_id=None if user.role == "STUDENT" else user.id,
            academic_year=academic_year,
            grade=grade,
            semester=semester,
            record_source=(
                "VOCATIONAL_TRAINING_RECORD" if is_vocational_term else "HOME_SCHOOL_RECORD"
            ),
            vocational_institution_name=("합성 직업교육기관" if is_vocational_term else None),
            is_vocational_training_semester=is_vocational_term,
            verification_status="USER_VERIFIED",
        )
        term_rows = tuple(
            row
            for row in DEMO_SCORE_ROWS
            if (row.academic_year, row.grade, row.semester) == (academic_year, grade, semester)
        )
        courses_by_record[record_id] = tuple(
            StudentCourseRecord(
                id=f"demo-course-{user.role.lower()}-{term_index}-{course_index}",
                academic_record_id=record_id,
                subject_group=row.subject_group,
                subject_name=row.subject_name,
                credits=Decimal(row.credits),
                raw_score=Decimal(row.raw_score) if row.raw_score else None,
                course_mean=Decimal(row.course_mean) if row.course_mean else None,
                standard_deviation=(
                    Decimal(row.standard_deviation) if row.standard_deviation else None
                ),
                rank_grade=Decimal(row.rank_grade),
                extraction_method="DEMO_SYNTHETIC",
                user_verified=True,
            )
            for course_index, row in enumerate(term_rows, start=1)
        )
        records.append(record)
    return tuple(records), courses_by_record


def demo_classroom_workspace(
    user: UserAccount,
) -> tuple[
    tuple[TeacherClassroom, ...],
    dict[str, tuple[ClassroomStudent, ...]],
    ClassroomStudent,
    tuple[StudentAcademicRecord, ...],
    dict[str, tuple[StudentCourseRecord, ...]],
]:
    classroom = TeacherClassroom(
        id=f"demo-class-{user.role.lower()}",
        teacher_user_account_id=user.id,
        academic_year=2027,
        department_name="합성 소프트웨어과",
        class_name="데모 3-A",
    )
    student = ClassroomStudent(
        id=f"demo-student-{user.role.lower()}",
        classroom_id=classroom.id,
        anonymous_code="DEMO-001",
        linked_user_account_id=None,
        link_code_digest=None,
        link_code_hint=None,
        link_code_expires_at=None,
        linked_at=None,
    )
    records, courses = demo_academic_records(
        user, student_id=classroom_student_reference(student.id)
    )
    return (classroom,), {classroom.id: (student,)}, student, records, courses


def demo_institutional_outcomes(user: UserAccount) -> tuple[InstitutionalOutcomeView, ...]:
    track = TrackOption(
        track_id="demo-synthetic-track",
        institution_id="demo-synthetic-institution",
        institution_name="합성 전문대학",
        campus_name="합성 캠퍼스",
        program_id="demo-synthetic-program",
        program_name="소프트웨어융합과",
        round_name="수시 1차",
        track_name="합성 일반전형",
    )
    outcome = InstitutionApplicationOutcome(
        id=f"demo-outcome-{user.role.lower()}",
        managed_by_user_account_id=user.id,
        anonymous_student_code="DEMO-001",
        academic_year=2027,
        admission_track_id=track.track_id,
        reflected_grade=Decimal("2.769"),
        outcome_status="UNKNOWN",
        initial_waitlist_number=None,
        final_waitlist_number=None,
        source_status="UNCONFIRMED",
        notes="실제 학생·대학 자료가 아닌 화면 체험용 합성 결과",
    )
    return (InstitutionalOutcomeView(outcome=outcome, track=track),)


__all__ = [
    "demo_academic_records",
    "demo_classroom_workspace",
    "demo_institutional_outcomes",
]
