from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP, Decimal

from app.services.score_inputs import (
    AcademicRecordInput,
    CourseRecordInput,
    ScoreInputSelection,
    ScoreInputStatus,
)
from app.services.score_rule_schema import ScoreRuleDefinition


@dataclass(frozen=True)
class ComparableCourseValue:
    course_record_id: str
    normalized_value: Decimal
    value_scale: str
    scope_codes: frozenset[str]

    def __post_init__(self) -> None:
        if not self.course_record_id or not self.value_scale:
            raise ValueError("비교값에는 과목 ID와 값 척도가 필요합니다.")
        if not self.normalized_value.is_finite():
            raise ValueError("비교값은 유한한 Decimal이어야 합니다.")


@dataclass(frozen=True)
class SelectedSemesterTrace:
    academic_year: int
    grade: int
    semester: int
    record_source: str
    comparison_value: Decimal
    selected_course_ids: tuple[str, ...]


@dataclass(frozen=True)
class ScoreSelectionTrace:
    value_direction: str
    semester_selection_method: str
    semester_selection_scope: str
    subject_selection_method: str
    value_scale: str | None
    semester_rounding_mode: str | None
    semester_rounding_scale: int | None
    selected_semesters: tuple[SelectedSemesterTrace, ...]
    exclusion_reasons: tuple[str, ...]


@dataclass(frozen=True)
class ScoreSelectionResult:
    status: ScoreInputStatus
    records: tuple[AcademicRecordInput, ...]
    trace: ScoreSelectionTrace


@dataclass(frozen=True)
class _ScoredRecord:
    record: AcademicRecordInput
    comparison_value: Decimal


def select_terms_and_subjects(
    selection: ScoreInputSelection,
    definition: ScoreRuleDefinition,
    course_values: Mapping[str, ComparableCourseValue],
) -> ScoreSelectionResult:
    if selection.status is not ScoreInputStatus.READY:
        return _result(
            selection.status,
            (),
            definition,
            value_scale=None,
            exclusion_reasons=(f"SOURCE_SELECTION_{selection.status.value}",),
        )
    if definition.semester_selection_method == "MANUAL_REVIEW" or (
        definition.subject_selection_method == "MANUAL_REVIEW"
        or definition.subject_scope == "MANUAL_REVIEW"
    ):
        return _result(
            ScoreInputStatus.NEEDS_REVIEW,
            (),
            definition,
            value_scale=None,
            exclusion_reasons=("SELECTION_MANUAL_REVIEW",),
        )

    included: list[AcademicRecordInput] = []
    exclusion_reasons: list[str] = []
    for record in sorted(selection.records, key=_record_key):
        include = _record_inclusion(record, definition)
        if include is None:
            return _result(
                ScoreInputStatus.NEEDS_REVIEW,
                (),
                definition,
                value_scale=None,
                exclusion_reasons=("INCLUSION_VALUE_MISSING",),
            )
        if not include:
            exclusion_reasons.append("TERM_EXCLUDED_BY_RULE")
            continue
        included.append(record)

    scored_records: list[_ScoredRecord] = []
    value_scales: set[str] = set()
    for record in included:
        selected_courses = []
        selected_values: list[ComparableCourseValue] = []
        for course in sorted(
            record.courses, key=lambda item: (item.subject_name, item.course_record_id)
        ):
            comparable = course_values.get(course.course_record_id)
            if comparable is None:
                return _result(
                    ScoreInputStatus.NEEDS_REVIEW,
                    (),
                    definition,
                    value_scale=None,
                    exclusion_reasons=("COMPARABLE_VALUE_MISSING",),
                )
            if definition.subject_scope != "ALL" and (
                definition.subject_scope not in comparable.scope_codes
            ):
                exclusion_reasons.append("SUBJECT_SCOPE_EXCLUDED")
                continue
            value_scales.add(comparable.value_scale)
            selected_courses.append(course)
            selected_values.append(comparable)

        if definition.subject_selection_method == "BEST_N":
            count = definition.best_subject_count
            if count is None or count <= 0:
                raise ValueError("BEST_N 과목 선택에는 양의 개수가 필요합니다.")
            ranked = sorted(
                zip(selected_courses, selected_values, strict=True),
                key=lambda item: (
                    _rank_value(item[1].normalized_value, definition.value_direction),
                    item[0].subject_name,
                    item[0].course_record_id,
                ),
            )[:count]
            selected_courses = [item[0] for item in ranked]
            selected_values = [item[1] for item in ranked]
        elif definition.subject_selection_method not in {"ALL", "SCOPE"}:
            raise ValueError("허용되지 않은 과목 선택 방법입니다.")

        if not selected_courses:
            exclusion_reasons.append("NO_SUBJECTS_SELECTED")
            continue
        if definition.minimum_semester_credits is not None:
            credits = tuple(course.credits for course in selected_courses)
            if any(credit is None or credit <= 0 for credit in credits):
                return _result(
                    ScoreInputStatus.NEEDS_REVIEW,
                    (),
                    definition,
                    value_scale=None,
                    exclusion_reasons=("CREDIT_VALUE_MISSING",),
                )
            total_credits = sum((credit for credit in credits if credit is not None), Decimal(0))
            if total_credits < definition.minimum_semester_credits:
                exclusion_reasons.append("MINIMUM_SEMESTER_CREDITS_NOT_MET")
                continue
        comparison = _semester_value(
            tuple(selected_courses), tuple(selected_values), definition.credit_weighted
        )
        if comparison is None:
            return _result(
                ScoreInputStatus.NEEDS_REVIEW,
                (),
                definition,
                value_scale=None,
                exclusion_reasons=("CREDIT_VALUE_MISSING",),
            )
        comparison = _round_semester_value(comparison, definition)
        scored_records.append(
            _ScoredRecord(
                record=AcademicRecordInput(
                    academic_record_id=record.academic_record_id,
                    academic_year=record.academic_year,
                    grade=record.grade,
                    semester=record.semester,
                    record_source=record.record_source,
                    is_vocational_training_semester=record.is_vocational_training_semester,
                    verification_status=record.verification_status,
                    courses=tuple(selected_courses),
                ),
                comparison_value=comparison,
            )
        )

    if len(value_scales) > 1:
        return _result(
            ScoreInputStatus.NEEDS_REVIEW,
            (),
            definition,
            value_scale=None,
            exclusion_reasons=("INCOMPARABLE_VALUE_SCALES",),
        )
    if not scored_records:
        return _result(
            ScoreInputStatus.INSUFFICIENT_DATA,
            (),
            definition,
            value_scale=next(iter(value_scales), None),
            exclusion_reasons=tuple(sorted(set(exclusion_reasons))),
        )

    selected_scored = _select_semesters(scored_records, definition)
    selected_scored.sort(key=lambda item: _record_key(item.record))
    records = tuple(item.record for item in selected_scored)
    return ScoreSelectionResult(
        status=ScoreInputStatus.READY,
        records=records,
        trace=ScoreSelectionTrace(
            value_direction=definition.value_direction,
            semester_selection_method=definition.semester_selection_method,
            semester_selection_scope=definition.semester_selection_scope,
            subject_selection_method=definition.subject_selection_method,
            value_scale=next(iter(value_scales), None),
            semester_rounding_mode=definition.semester_rounding_mode,
            semester_rounding_scale=definition.semester_rounding_scale,
            selected_semesters=tuple(
                SelectedSemesterTrace(
                    academic_year=item.record.academic_year,
                    grade=item.record.grade,
                    semester=item.record.semester,
                    record_source=item.record.record_source,
                    comparison_value=item.comparison_value,
                    selected_course_ids=tuple(
                        course.course_record_id for course in item.record.courses
                    ),
                )
                for item in selected_scored
            ),
            exclusion_reasons=tuple(sorted(set(exclusion_reasons))),
        ),
    )


def _record_inclusion(record: AcademicRecordInput, definition: ScoreRuleDefinition) -> bool | None:
    if record.record_source == "HOME_SCHOOL_RECORD":
        if record.grade == 1:
            return definition.home_grade_1_included
        if record.grade == 2:
            return definition.home_grade_2_included
        if record.grade == 3 and record.semester == 1:
            return definition.home_grade_3_semester_1_included
        if record.grade == 3 and record.semester == 2:
            return definition.home_grade_3_semester_2_included
        return False
    if record.record_source == "VOCATIONAL_TRAINING_RECORD":
        if definition.vocational_grade_included is not True:
            return definition.vocational_grade_included
        if record.semester == 1:
            return definition.vocational_semester_1_included
        if record.semester == 2:
            return definition.vocational_semester_2_included
    return False


def _semester_value(
    courses: tuple[CourseRecordInput, ...],
    values: tuple[ComparableCourseValue, ...],
    credit_weighted: bool | None,
) -> Decimal | None:
    if credit_weighted is None:
        return None
    if not credit_weighted:
        return sum(value.normalized_value for value in values) / Decimal(len(values))
    credits = [course.credits for course in courses]
    if any(credit is None or credit <= 0 for credit in credits):
        return None
    total_credits = sum((credit for credit in credits if credit is not None), Decimal(0))
    return (
        sum(
            value.normalized_value * credit
            for value, credit in zip(values, credits, strict=True)
            if credit is not None
        )
        / total_credits
    )


def _select_semesters(
    records: list[_ScoredRecord], definition: ScoreRuleDefinition
) -> list[_ScoredRecord]:
    method = definition.semester_selection_method
    if definition.semester_selection_scope == "PER_GRADE" and method != "BEST_N":
        raise ValueError("PER_GRADE 학기 선택 범위는 BEST_N에만 사용할 수 있습니다.")
    if method == "ALL":
        return list(records)
    count = definition.best_semester_count
    if count is None or count <= 0:
        raise ValueError(f"{method} 학기 선택에는 양의 개수가 필요합니다.")
    ordered = sorted(records, key=lambda item: _record_key(item.record))
    if method == "FIRST_N":
        return ordered[:count]
    if method == "RECENT_N":
        return ordered[-count:]
    if method == "BEST_N":
        if definition.semester_selection_scope == "GLOBAL":
            return _rank_semesters(records, definition)[:count]
        if definition.semester_selection_scope == "PER_GRADE":
            by_grade: dict[int, list[_ScoredRecord]] = {}
            for item in records:
                by_grade.setdefault(item.record.grade, []).append(item)
            return [
                item
                for grade in sorted(by_grade)
                for item in _rank_semesters(by_grade[grade], definition)[:count]
            ]
        raise ValueError("허용되지 않은 학기 선택 범위입니다.")
    raise ValueError("허용되지 않은 학기 선택 방법입니다.")


def _round_semester_value(value: Decimal, definition: ScoreRuleDefinition) -> Decimal:
    mode = definition.semester_rounding_mode
    scale = definition.semester_rounding_scale
    if mode is None and scale is None:
        return value
    if mode is None or scale is None or not 0 <= scale <= 12:
        raise ValueError("학기 평균 반올림 방식과 자릿수가 모두 필요합니다.")
    modes = {
        "ROUND_HALF_UP": ROUND_HALF_UP,
        "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
        "ROUND_DOWN": ROUND_DOWN,
        "ROUND_UP": ROUND_UP,
        "TRUNCATE": ROUND_DOWN,
    }
    try:
        decimal_mode = modes[mode]
    except KeyError as error:
        raise ValueError(f"허용되지 않은 학기 평균 반올림 방식입니다: {mode}") from error
    return value.quantize(Decimal(1).scaleb(-scale), rounding=decimal_mode)


def _record_key(record: AcademicRecordInput) -> tuple[int, int, int, str, str]:
    return (
        record.grade,
        record.semester,
        record.academic_year,
        record.record_source,
        record.academic_record_id,
    )


def _rank_semesters(
    records: list[_ScoredRecord], definition: ScoreRuleDefinition
) -> list[_ScoredRecord]:
    return sorted(
        records,
        key=lambda item: (
            _rank_value(item.comparison_value, definition.value_direction),
            _record_key(item.record),
        ),
    )


def _rank_value(value: Decimal, direction: str) -> Decimal:
    if direction == "HIGHER_IS_BETTER":
        return -value
    if direction == "LOWER_IS_BETTER":
        return value
    raise ValueError("허용되지 않은 값 우선 방향입니다.")


def _result(
    status: ScoreInputStatus,
    records: tuple[AcademicRecordInput, ...],
    definition: ScoreRuleDefinition,
    *,
    value_scale: str | None,
    exclusion_reasons: tuple[str, ...],
) -> ScoreSelectionResult:
    return ScoreSelectionResult(
        status=status,
        records=records,
        trace=ScoreSelectionTrace(
            value_direction=definition.value_direction,
            semester_selection_method=definition.semester_selection_method,
            semester_selection_scope=definition.semester_selection_scope,
            subject_selection_method=definition.subject_selection_method,
            value_scale=value_scale,
            semester_rounding_mode=definition.semester_rounding_mode,
            semester_rounding_scale=definition.semester_rounding_scale,
            selected_semesters=(),
            exclusion_reasons=exclusion_reasons,
        ),
    )


__all__ = [
    "ComparableCourseValue",
    "ScoreSelectionResult",
    "ScoreSelectionTrace",
    "SelectedSemesterTrace",
    "select_terms_and_subjects",
]
