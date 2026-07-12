from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StudentAcademicRecord, StudentCourseRecord
from app.services.eligibility import EligibilityDecision, require_score_calculation_allowed
from app.services.published_rules import (
    PublishedRule,
    load_published_grade_source_scope_rule,
    require_published_rule_usable,
)


class ScopeRuleSchemaError(ValueError):
    pass


class GradeSourcePolicy(StrEnum):
    HOME_ONLY = "HOME_ONLY"
    VOCATIONAL_INCLUDED = "VOCATIONAL_INCLUDED"
    VOCATIONAL_ONLY = "VOCATIONAL_ONLY"
    EXCLUDE_VOCATIONAL_SEMESTER = "EXCLUDE_VOCATIONAL_SEMESTER"
    TRACK_DEPENDENT = "TRACK_DEPENDENT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ScoreInputStatus(StrEnum):
    READY = "READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass(frozen=True)
class CourseRecordInput:
    course_record_id: str
    subject_group: str | None
    subject_name: str
    credits: Decimal | None
    raw_score: Decimal | None
    raw_score_label: str | None
    course_mean: Decimal | None
    standard_deviation: Decimal | None
    achievement_level: str | None
    enrollment_count: int | None
    rank_grade: Decimal | None
    user_verified: bool


@dataclass(frozen=True)
class AcademicRecordInput:
    academic_record_id: str
    academic_year: int
    grade: int
    semester: int
    record_source: str
    is_vocational_training_semester: bool
    verification_status: str
    courses: tuple[CourseRecordInput, ...]


@dataclass(frozen=True)
class SelectedTermTrace:
    academic_year: int
    grade: int
    semester: int
    record_source: str
    subjects: tuple[str, ...]


@dataclass(frozen=True)
class ScoreInputTrace:
    rule_id: str
    rule_version: str
    policy: GradeSourcePolicy
    selected_sources: tuple[str, ...]
    selected_terms: tuple[SelectedTermTrace, ...]
    exclusion_reasons: tuple[str, ...]


@dataclass(frozen=True)
class ScoreInputSelection:
    status: ScoreInputStatus
    records: tuple[AcademicRecordInput, ...]
    trace: ScoreInputTrace


def select_score_inputs(
    *,
    records: tuple[AcademicRecordInput, ...],
    rule: PublishedRule,
    eligibility: EligibilityDecision,
) -> ScoreInputSelection:
    require_score_calculation_allowed(eligibility)
    require_published_rule_usable(rule)
    policy = validate_grade_source_scope_payload(rule.payload)
    if policy in {GradeSourcePolicy.TRACK_DEPENDENT, GradeSourcePolicy.MANUAL_REVIEW}:
        return _selection(
            rule,
            policy,
            status=ScoreInputStatus.NEEDS_REVIEW,
            records=(),
            exclusion_reasons=(policy.value,),
        )

    selected: list[AcademicRecordInput] = []
    exclusion_reasons: list[str] = []
    ordered_records = sorted(
        records,
        key=lambda record: (
            record.academic_year,
            record.grade,
            record.semester,
            record.record_source,
            record.academic_record_id,
        ),
    )
    for record in ordered_records:
        exclusion_reason = _record_exclusion_reason(record, policy)
        if exclusion_reason is not None:
            exclusion_reasons.append(exclusion_reason)
            continue
        verified_courses = tuple(
            sorted(
                (course for course in record.courses if course.user_verified),
                key=lambda course: (course.subject_name, course.course_record_id),
            )
        )
        if len(verified_courses) != len(record.courses):
            exclusion_reasons.append("COURSE_NOT_VERIFIED")
        if not verified_courses:
            exclusion_reasons.append("NO_VERIFIED_COURSES")
            continue
        selected.append(
            AcademicRecordInput(
                academic_record_id=record.academic_record_id,
                academic_year=record.academic_year,
                grade=record.grade,
                semester=record.semester,
                record_source=record.record_source,
                is_vocational_training_semester=record.is_vocational_training_semester,
                verification_status=record.verification_status,
                courses=verified_courses,
            )
        )

    selected_records = tuple(selected)
    return _selection(
        rule,
        policy,
        status=ScoreInputStatus.READY if selected_records else ScoreInputStatus.INSUFFICIENT_DATA,
        records=selected_records,
        exclusion_reasons=tuple(sorted(set(exclusion_reasons))),
    )


def evaluate_published_score_inputs(
    session: Session,
    admission_track_id: str,
    student_id: str,
    eligibility: EligibilityDecision,
) -> ScoreInputSelection:
    require_score_calculation_allowed(eligibility)
    rule = load_published_grade_source_scope_rule(session, admission_track_id)
    records = load_academic_record_inputs(session, student_id)
    return select_score_inputs(records=records, rule=rule, eligibility=eligibility)


def load_academic_record_inputs(
    session: Session, student_id: str
) -> tuple[AcademicRecordInput, ...]:
    normalized_student_id = student_id.strip()
    if not normalized_student_id:
        raise ValueError("내부 학생 식별자가 필요합니다.")
    academic_records = session.scalars(
        select(StudentAcademicRecord)
        .where(StudentAcademicRecord.student_id == normalized_student_id)
        .order_by(
            StudentAcademicRecord.academic_year,
            StudentAcademicRecord.grade,
            StudentAcademicRecord.semester,
            StudentAcademicRecord.record_source,
            StudentAcademicRecord.id,
        )
    ).all()
    if not academic_records:
        return ()
    record_ids = [record.id for record in academic_records]
    courses = session.scalars(
        select(StudentCourseRecord)
        .where(StudentCourseRecord.academic_record_id.in_(record_ids))
        .order_by(StudentCourseRecord.subject_name, StudentCourseRecord.id)
    ).all()
    courses_by_record: dict[str, list[CourseRecordInput]] = {
        record_id: [] for record_id in record_ids
    }
    for course in courses:
        courses_by_record[course.academic_record_id].append(
            CourseRecordInput(
                course_record_id=course.id,
                subject_group=course.subject_group,
                subject_name=course.subject_name,
                credits=course.credits,
                raw_score=course.raw_score,
                raw_score_label=course.raw_score_label,
                course_mean=course.course_mean,
                standard_deviation=course.standard_deviation,
                achievement_level=course.achievement_level,
                enrollment_count=course.enrollment_count,
                rank_grade=course.rank_grade,
                user_verified=course.user_verified,
            )
        )
    return tuple(
        AcademicRecordInput(
            academic_record_id=record.id,
            academic_year=record.academic_year,
            grade=record.grade,
            semester=record.semester,
            record_source=record.record_source,
            is_vocational_training_semester=record.is_vocational_training_semester,
            verification_status=record.verification_status,
            courses=tuple(courses_by_record[record.id]),
        )
        for record in academic_records
    )


def validate_grade_source_scope_payload(payload: dict[str, object]) -> GradeSourcePolicy:
    if set(payload) != {"schema_version", "policy"}:
        raise ScopeRuleSchemaError("성적 출처 범위 payload 필드가 계약과 다릅니다.")
    if payload.get("schema_version") != 1:
        raise ScopeRuleSchemaError("성적 출처 범위 schema_version은 1이어야 합니다.")
    raw_policy = payload.get("policy")
    if not isinstance(raw_policy, str):
        raise ScopeRuleSchemaError("성적 출처 범위 policy는 문자열이어야 합니다.")
    try:
        return GradeSourcePolicy(raw_policy)
    except ValueError as error:
        raise ScopeRuleSchemaError(f"허용되지 않은 성적 출처 범위입니다: {raw_policy}") from error


def _record_exclusion_reason(record: AcademicRecordInput, policy: GradeSourcePolicy) -> str | None:
    if record.verification_status != "USER_VERIFIED":
        return "ACADEMIC_RECORD_NOT_VERIFIED"
    if record.record_source not in {
        "HOME_SCHOOL_RECORD",
        "VOCATIONAL_TRAINING_RECORD",
    }:
        return "SOURCE_OUT_OF_SCOPE"
    if policy is GradeSourcePolicy.HOME_ONLY:
        return None if record.record_source == "HOME_SCHOOL_RECORD" else "SOURCE_OUT_OF_SCOPE"
    if policy is GradeSourcePolicy.VOCATIONAL_ONLY:
        return (
            None if record.record_source == "VOCATIONAL_TRAINING_RECORD" else "SOURCE_OUT_OF_SCOPE"
        )
    if policy is GradeSourcePolicy.EXCLUDE_VOCATIONAL_SEMESTER:
        return "VOCATIONAL_SEMESTER_EXCLUDED" if record.is_vocational_training_semester else None
    return None


def _selection(
    rule: PublishedRule,
    policy: GradeSourcePolicy,
    *,
    status: ScoreInputStatus,
    records: tuple[AcademicRecordInput, ...],
    exclusion_reasons: tuple[str, ...],
) -> ScoreInputSelection:
    return ScoreInputSelection(
        status=status,
        records=records,
        trace=ScoreInputTrace(
            rule_id=rule.rule_id,
            rule_version=rule.version,
            policy=policy,
            selected_sources=tuple(dict.fromkeys(record.record_source for record in records)),
            selected_terms=tuple(
                SelectedTermTrace(
                    academic_year=record.academic_year,
                    grade=record.grade,
                    semester=record.semester,
                    record_source=record.record_source,
                    subjects=tuple(course.subject_name for course in record.courses),
                )
                for record in records
            ),
            exclusion_reasons=exclusion_reasons,
        ),
    )


__all__ = [
    "AcademicRecordInput",
    "CourseRecordInput",
    "GradeSourcePolicy",
    "ScopeRuleSchemaError",
    "ScoreInputSelection",
    "ScoreInputStatus",
    "evaluate_published_score_inputs",
    "load_academic_record_inputs",
    "select_score_inputs",
    "validate_grade_source_scope_payload",
]
