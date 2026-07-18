from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from app.services.score_calculation import (
    ScoreCalculationError,
    ScoreCalculationResult,
    calculate_reflected_grade,
    calculate_selected_score,
)
from app.services.score_components import (
    AttendanceInput,
    AttendanceTableRow,
    convert_attendance,
)
from app.services.score_rule_schema import ScoreRuleDefinition
from app.services.score_selection import ScoreSelectionResult, select_terms_and_subjects
from tests.test_score_selection import _definition, _selection, _values


def _selected(
    definition: ScoreRuleDefinition | None = None,
) -> tuple[ScoreSelectionResult, ScoreRuleDefinition]:
    effective = definition or _definition()
    return select_terms_and_subjects(_selection(), effective, _values()), effective


def _calculate(
    selection: ScoreSelectionResult, definition: ScoreRuleDefinition
) -> ScoreCalculationResult:
    return calculate_selected_score(
        selection,
        definition,
        rule_id="synthetic-score-rule",
        rule_version="synthetic-v1",
    )


def test_equal_weight_calculation_is_decimal_and_reproducible() -> None:
    selection, definition = _selected()

    first = _calculate(selection, definition)
    second = _calculate(selection, definition)

    assert first.final_score == Decimal("74.00")
    assert first == second


def test_grade_weights_apply_after_semester_selection() -> None:
    definition = replace(
        _definition(),
        weighting_mode="GRADE_ONLY",
        grade_weight_1=Decimal("0.30"),
        grade_weight_2=Decimal("0.30"),
        grade_weight_3=Decimal("0.40"),
    )
    selection, definition = _selected(definition)

    result = _calculate(selection, definition)

    assert result.final_score == Decimal("74.25")
    assert result.trace.weighting_mode == "GRADE_ONLY"


def test_grade_average_rounding_is_applied_before_grade_weights() -> None:
    definition = replace(
        _definition(),
        weighting_mode="GRADE_ONLY",
        semester_rounding_mode="ROUND_HALF_UP",
        semester_rounding_scale=4,
        grade_rounding_mode="ROUND_HALF_UP",
        grade_rounding_scale=2,
        grade_weight_1=Decimal("0.30"),
        grade_weight_2=Decimal("0.30"),
        grade_weight_3=Decimal("0.40"),
    )
    values = _values()
    values["course-1-1-a"] = replace(values["course-1-1-a"], normalized_value=Decimal("60.00999"))
    selection = select_terms_and_subjects(_selection(), definition, values)

    result = _calculate(selection, definition)

    grade_one = next(
        component for component in result.trace.components if component.key == "grade_1"
    )
    assert grade_one.value == Decimal("75.00")
    assert result.trace.grade_rounding_mode == "ROUND_HALF_UP"
    assert result.trace.grade_rounding_scale == 2


def test_semester_weights_apply_to_exact_selected_terms() -> None:
    definition = replace(
        _definition(),
        weighting_mode="GLOBAL_SEMESTER",
        semester_weight_1_1=Decimal("0.10"),
        semester_weight_1_2=Decimal("0.10"),
        semester_weight_2_1=Decimal("0.20"),
        semester_weight_2_2=Decimal("0.30"),
        semester_weight_3_1=Decimal("0.30"),
    )
    selection, definition = _selected(definition)

    result = _calculate(selection, definition)

    assert result.final_score == Decimal("75.50")
    assert result.trace.weighting_mode == "GLOBAL_SEMESTER"


def test_missing_or_conflicting_weight_is_never_guessed() -> None:
    definition = replace(
        _definition(),
        weighting_mode="GLOBAL_SEMESTER",
        semester_weight_1_1=Decimal("0.50"),
        semester_weight_1_2=Decimal("0.50"),
    )
    selection, definition = _selected(definition)

    with pytest.raises(ScoreCalculationError):
        _calculate(selection, definition)


def test_grade_and_within_grade_semester_weights_are_applied_hierarchically() -> None:
    definition = replace(
        _definition(),
        weighting_mode="GRADE_WITHIN_SEMESTER",
        grade_weight_1=Decimal("0.30"),
        grade_weight_2=Decimal("0.30"),
        grade_weight_3=Decimal("0.40"),
        semester_weight_1_1=Decimal("0.40"),
        semester_weight_1_2=Decimal("0.60"),
        semester_weight_2_1=Decimal("0.25"),
        semester_weight_2_2=Decimal("0.75"),
        semester_weight_3_1=Decimal("1"),
        semester_weight_3_2=Decimal("0"),
    )
    selection, definition = _selected(definition)

    result = _calculate(selection, definition)

    assert result.final_score == Decimal("77.18")
    assert result.trace.weighting_mode == "GRADE_WITHIN_SEMESTER"
    assert sum(component.weight for component in result.trace.components) == Decimal("1.0000")


def test_rounding_modes_are_applied_only_at_declared_final_stage() -> None:
    definition = replace(_definition(), rounding_scale=1, rounding_mode="ROUND_DOWN")
    values = _values()
    values["course-1-1-a"] = replace(values["course-1-1-a"], normalized_value=Decimal("60.19"))
    selection = select_terms_and_subjects(_selection(), definition, values)

    result = _calculate(selection, definition)

    assert result.final_score == result.pre_round_score.quantize(
        Decimal("0.1"), rounding="ROUND_DOWN"
    )


def test_display_only_rounding_does_not_change_calculation_value() -> None:
    definition = replace(
        _definition(),
        rounding_stage="DISPLAY_ONLY",
        rounding_scale=None,
        display_scale=1,
    )
    values = _values()
    values["course-1-1-a"] = replace(values["course-1-1-a"], normalized_value=Decimal("60.19"))
    selection = select_terms_and_subjects(_selection(), definition, values)

    result = _calculate(selection, definition)

    assert result.final_score == result.pre_round_score
    assert result.display_score == result.pre_round_score.quantize(Decimal("0.1"))


def test_limited_linear_transform_converts_aggregate_without_free_formula() -> None:
    definition = replace(
        _definition(),
        score_transform_mode="LINEAR",
        score_base=Decimal("100"),
        score_multiplier=Decimal("-1"),
    )
    selection, definition = _selected(definition)

    result = _calculate(selection, definition)

    assert result.trace.aggregate_value == Decimal("74.0")
    assert result.pre_round_score == Decimal("26.0")
    assert result.final_score == Decimal("26.00")


def test_reflected_grade_is_not_changed_by_point_linear_transform() -> None:
    definition = replace(
        _definition(),
        value_direction="LOWER_IS_BETTER",
        score_transform_mode="LINEAR",
        score_base=Decimal("100"),
        score_multiplier=Decimal("-1"),
    )
    grade_values = {
        course_id: replace(
            value,
            normalized_value=Decimal(index % 5 + 1),
            value_scale="RANK_GRADE",
        )
        for index, (course_id, value) in enumerate(_values().items())
    }
    source = _selection()
    source = replace(
        source,
        records=tuple(
            replace(
                record,
                courses=tuple(
                    replace(
                        course,
                        rank_grade=grade_values[course.course_record_id].normalized_value,
                    )
                    for course in record.courses
                ),
            )
            for record in source.records
        ),
    )
    selection = select_terms_and_subjects(source, definition, grade_values)

    reflected = calculate_reflected_grade(
        selection,
        definition,
        rule_id="synthetic-score-rule",
        rule_version="synthetic-v1",
    )
    point_score = _calculate(selection, definition)

    assert reflected.unrounded_average_grade == Decimal("3")
    assert reflected.final_average_grade == Decimal("3")
    assert reflected.display_average_grade == Decimal("3.00")
    assert point_score.trace.aggregate_value == reflected.unrounded_average_grade
    assert point_score.final_score == Decimal("97.00")


@pytest.mark.parametrize(
    ("value_scale", "rank_grade"),
    (("RANK_GRADE=74", Decimal("4")), ("RANK_GRADE", Decimal("74"))),
)
def test_reflected_grade_rejects_unapproved_scale_and_out_of_range_values(
    value_scale: str, rank_grade: Decimal
) -> None:
    definition = replace(_definition(), value_direction="LOWER_IS_BETTER")
    source = _selection()
    source = replace(
        source,
        records=tuple(
            replace(
                record,
                courses=tuple(replace(course, rank_grade=rank_grade) for course in record.courses),
            )
            for record in source.records
        ),
    )
    grade_values = {
        course_id: replace(
            value,
            normalized_value=rank_grade,
            value_scale=value_scale,
        )
        for course_id, value in _values().items()
    }
    selection = select_terms_and_subjects(source, definition, grade_values)

    with pytest.raises(ScoreCalculationError):
        calculate_reflected_grade(
            selection,
            definition,
            rule_id="synthetic-score-rule",
            rule_version="synthetic-v1",
        )


def test_interview_and_practical_ratios_do_not_change_predicted_score() -> None:
    selection, definition = _selected()
    with_components = replace(
        definition,
        interview_ratio=Decimal("0.20"),
        practical_ratio=Decimal("0.30"),
    )

    base = _calculate(selection, definition)
    informational = _calculate(selection, with_components)

    assert informational.final_score == base.final_score
    assert informational.trace.non_predictive_components == (
        ("interview_ratio", Decimal("0.20")),
        ("practical_ratio", Decimal("0.30")),
    )
    assert informational.trace.rule_version == "synthetic-v1"


def test_verified_attendance_is_added_separately_with_table_trace() -> None:
    definition = replace(
        _definition(),
        attendance_included=True,
        attendance_table_code="SYNTHETIC_ATTENDANCE_V1",
        attendance_source="UNIVERSITY_OFFICIAL",
        attendance_minor_event_conversion_unit=3,
        maximum_score=Decimal("120"),
    )
    selection, definition = _selected(definition)
    attendance = convert_attendance(
        attendance=AttendanceInput(1, 2, 1, 0, True),
        table_rows=(
            AttendanceTableRow(
                table_code="SYNTHETIC_ATTENDANCE_V1",
                absence_min=0,
                absence_max=None,
                score=Decimal("18"),
                maximum_score=Decimal("20"),
                evidence_document_id="synthetic-guide",
                evidence_page=10,
                evidence_location="합성 출결 표",
                source_status="FINAL_GUIDE",
            ),
        ),
        table_code="SYNTHETIC_ATTENDANCE_V1",
        table_version="synthetic-v1",
        source="UNIVERSITY_OFFICIAL",
        minor_event_conversion_unit=3,
    )

    result = calculate_selected_score(
        selection,
        definition,
        rule_id="synthetic-score-rule",
        rule_version="synthetic-v1",
        attendance=attendance,
    )

    assert result.trace.academic_score == Decimal("74.0")
    assert result.trace.attendance_score == Decimal("18")
    assert result.final_score == Decimal("92.00")
    assert result.trace.attendance_table_version == "synthetic-v1"


def test_attendance_is_not_guessed_or_added_to_non_attendance_rule() -> None:
    selection, definition = _selected(replace(_definition(), attendance_included=True))
    with pytest.raises(ScoreCalculationError):
        _calculate(selection, definition)
