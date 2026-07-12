from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.services.score_inputs import (
    AcademicRecordInput,
    CourseRecordInput,
    GradeSourcePolicy,
    ScoreInputSelection,
    ScoreInputStatus,
    ScoreInputTrace,
)
from app.services.score_rule_schema import ScoreRuleDefinition
from app.services.score_selection import (
    ComparableCourseValue,
    select_terms_and_subjects,
)


def _course(course_id: str, name: str, credits: str = "1") -> CourseRecordInput:
    return CourseRecordInput(
        course_record_id=course_id,
        subject_group="합성 교과",
        subject_name=name,
        credits=Decimal(credits),
        raw_score=None,
        raw_score_label=None,
        course_mean=None,
        standard_deviation=None,
        achievement_level=None,
        enrollment_count=None,
        rank_grade=None,
        user_verified=True,
    )


def _selection() -> ScoreInputSelection:
    records = tuple(
        AcademicRecordInput(
            academic_record_id=f"record-{grade}-{semester}",
            academic_year=2023 + grade,
            grade=grade,
            semester=semester,
            record_source="HOME_SCHOOL_RECORD",
            is_vocational_training_semester=False,
            verification_status="USER_VERIFIED",
            courses=(
                _course(f"course-{grade}-{semester}-a", f"합성 {grade}-{semester} A", "1"),
                _course(f"course-{grade}-{semester}-b", f"합성 {grade}-{semester} B", "3"),
            ),
        )
        for grade, semester in ((1, 1), (1, 2), (2, 1), (2, 2), (3, 1))
    )
    return ScoreInputSelection(
        status=ScoreInputStatus.READY,
        records=records,
        trace=ScoreInputTrace(
            rule_id="synthetic-scope",
            rule_version="v1",
            policy=GradeSourcePolicy.HOME_ONLY,
            selected_sources=("HOME_SCHOOL_RECORD",),
            selected_terms=(),
            exclusion_reasons=(),
        ),
    )


def _definition() -> ScoreRuleDefinition:
    return ScoreRuleDefinition(
        home_grade_1_included=True,
        home_grade_2_included=True,
        home_grade_3_semester_1_included=True,
        home_grade_3_semester_2_included=False,
        vocational_grade_included=False,
        vocational_semester_1_included=False,
        vocational_semester_2_included=False,
        value_direction="HIGHER_IS_BETTER",
        semester_selection_method="ALL",
        semester_selection_scope="GLOBAL",
        best_semester_count=None,
        subject_selection_method="ALL",
        best_subject_count=None,
        subject_scope="ALL",
        credit_weighted=False,
        semester_rounding_mode=None,
        semester_rounding_scale=None,
        grade_weight_1=None,
        grade_weight_2=None,
        grade_weight_3=None,
        semester_weight_1_1=None,
        semester_weight_1_2=None,
        semester_weight_2_1=None,
        semester_weight_2_2=None,
        semester_weight_3_1=None,
        semester_weight_3_2=None,
        weighting_mode="EQUAL",
        achievement_handling="EXCLUDE",
        achievement_table_code=None,
        achievement_source=None,
        achievement_distribution_scale=None,
        career_subject_included=False,
        z_score_policy="NOT_USED",
        z_score_source=None,
        z_score_table_code=None,
        z_score_formula_version=None,
        z_score_rounding_mode=None,
        z_score_rounding_scale=None,
        z_score_clip_min=None,
        z_score_clip_max=None,
        attendance_included=False,
        attendance_table_code=None,
        attendance_source=None,
        attendance_minor_event_conversion_unit=None,
        interview_ratio=None,
        practical_ratio=None,
        rounding_mode="ROUND_HALF_UP",
        rounding_stage="FINAL",
        rounding_scale=2,
        display_scale=2,
        score_transform_mode="IDENTITY",
        score_base=None,
        score_multiplier=None,
        maximum_score=Decimal("100"),
    )


def _values() -> dict[str, ComparableCourseValue]:
    values: dict[str, ComparableCourseValue] = {}
    semester_values = {
        (1, 1): ("60", "80"),
        (1, 2): ("70", "90"),
        (2, 1): ("50", "60"),
        (2, 2): ("95", "85"),
        (3, 1): ("75", "75"),
    }
    for (grade, semester), pair in semester_values.items():
        for suffix, value in zip(("a", "b"), pair, strict=True):
            values[f"course-{grade}-{semester}-{suffix}"] = ComparableCourseValue(
                course_record_id=f"course-{grade}-{semester}-{suffix}",
                normalized_value=Decimal(value),
                value_scale="SYNTHETIC_HIGHER_IS_BETTER",
                scope_codes=frozenset({"GENERAL_SUBJECTS", "SPECIFIED"}),
            )
    return values


def test_first_four_and_recent_four_semesters_are_deterministic() -> None:
    first = select_terms_and_subjects(
        _selection(),
        replace(_definition(), semester_selection_method="FIRST_N", best_semester_count=4),
        _values(),
    )
    recent = select_terms_and_subjects(
        _selection(),
        replace(_definition(), semester_selection_method="RECENT_N", best_semester_count=4),
        _values(),
    )

    assert [(row.grade, row.semester) for row in first.records] == [(1, 1), (1, 2), (2, 1), (2, 2)]
    assert [(row.grade, row.semester) for row in recent.records] == [(1, 2), (2, 1), (2, 2), (3, 1)]


def test_best_one_and_two_semesters_use_decimal_values() -> None:
    best_one = select_terms_and_subjects(
        _selection(),
        replace(_definition(), semester_selection_method="BEST_N", best_semester_count=1),
        _values(),
    )
    best_two = select_terms_and_subjects(
        _selection(),
        replace(_definition(), semester_selection_method="BEST_N", best_semester_count=2),
        _values(),
    )

    assert [(row.grade, row.semester) for row in best_one.records] == [(2, 2)]
    assert [(row.grade, row.semester) for row in best_two.records] == [(1, 2), (2, 2)]


def test_best_semester_can_be_selected_per_grade() -> None:
    result = select_terms_and_subjects(
        _selection(),
        replace(
            _definition(),
            semester_selection_method="BEST_N",
            semester_selection_scope="PER_GRADE",
            best_semester_count=1,
        ),
        _values(),
    )

    assert [(row.grade, row.semester) for row in result.records] == [
        (1, 2),
        (2, 2),
        (3, 1),
    ]


def test_lower_value_can_be_declared_as_better_without_negating_source_values() -> None:
    result = select_terms_and_subjects(
        _selection(),
        replace(
            _definition(),
            value_direction="LOWER_IS_BETTER",
            semester_selection_method="BEST_N",
            semester_selection_scope="PER_GRADE",
            best_semester_count=1,
        ),
        _values(),
    )

    assert [(row.grade, row.semester) for row in result.records] == [
        (1, 1),
        (2, 1),
        (3, 1),
    ]


def test_best_subject_count_is_applied_per_selected_semester() -> None:
    result = select_terms_and_subjects(
        _selection(),
        replace(_definition(), subject_selection_method="BEST_N", best_subject_count=1),
        _values(),
    )

    assert all(len(record.courses) == 1 for record in result.records)
    assert result.records[0].courses[0].course_record_id == "course-1-1-b"


def test_credit_weighted_semester_value_changes_ranking() -> None:
    unweighted = select_terms_and_subjects(
        _selection(),
        replace(_definition(), semester_selection_method="BEST_N", best_semester_count=1),
        _values(),
    )
    weighted_values = _values()
    weighted_values["course-2-2-a"] = replace(
        weighted_values["course-2-2-a"], normalized_value=Decimal("100")
    )
    weighted_values["course-2-2-b"] = replace(
        weighted_values["course-2-2-b"], normalized_value=Decimal("0")
    )
    weighted = select_terms_and_subjects(
        _selection(),
        replace(
            _definition(),
            semester_selection_method="BEST_N",
            best_semester_count=1,
            credit_weighted=True,
        ),
        weighted_values,
    )

    assert [(row.grade, row.semester) for row in unweighted.records] == [(2, 2)]
    assert [(row.grade, row.semester) for row in weighted.records] == [(1, 2)]


def test_semester_rounding_is_applied_before_ranking_and_recorded_in_trace() -> None:
    values = _values()
    values["course-1-1-a"] = replace(values["course-1-1-a"], normalized_value=Decimal("60.19"))
    result = select_terms_and_subjects(
        _selection(),
        replace(
            _definition(),
            semester_rounding_mode="ROUND_HALF_UP",
            semester_rounding_scale=1,
        ),
        values,
    )

    assert result.trace.selected_semesters[0].comparison_value == Decimal("70.1")


def test_scope_filter_uses_explicit_codes_not_subject_name_guessing() -> None:
    values = _values()
    values["course-1-1-a"] = replace(
        values["course-1-1-a"], scope_codes=frozenset({"CAREER_SUBJECTS"})
    )
    result = select_terms_and_subjects(
        _selection(),
        replace(_definition(), subject_selection_method="SCOPE", subject_scope="GENERAL_SUBJECTS"),
        values,
    )

    assert "course-1-1-a" not in {
        course.course_record_id for record in result.records for course in record.courses
    }


def test_excluded_subject_scale_does_not_affect_selected_scale() -> None:
    values = _values()
    values["course-1-1-a"] = replace(
        values["course-1-1-a"],
        value_scale="EXCLUDED_OTHER_SCALE",
        scope_codes=frozenset({"CAREER_SUBJECTS"}),
    )

    result = select_terms_and_subjects(
        _selection(),
        replace(_definition(), subject_selection_method="SCOPE", subject_scope="GENERAL_SUBJECTS"),
        values,
    )

    assert result.status is ScoreInputStatus.READY
    assert result.trace.value_scale == "SYNTHETIC_HIGHER_IS_BETTER"


def test_missing_comparable_value_and_unknown_inclusion_require_review() -> None:
    values = _values()
    values.pop("course-1-1-a")
    missing_value = select_terms_and_subjects(_selection(), _definition(), values)
    unknown_inclusion = select_terms_and_subjects(
        _selection(), replace(_definition(), home_grade_1_included=None), _values()
    )

    assert missing_value.status is ScoreInputStatus.NEEDS_REVIEW
    assert unknown_inclusion.status is ScoreInputStatus.NEEDS_REVIEW


def test_input_order_and_ties_produce_same_trace() -> None:
    selection = _selection()
    reversed_selection = replace(selection, records=tuple(reversed(selection.records)))
    definition = replace(_definition(), semester_selection_method="BEST_N", best_semester_count=2)

    first = select_terms_and_subjects(selection, definition, _values())
    second = select_terms_and_subjects(reversed_selection, definition, _values())

    assert first.records == second.records
    assert first.trace == second.trace
