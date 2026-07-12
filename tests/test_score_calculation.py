from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from app.services.score_calculation import (
    ScoreCalculationError,
    ScoreCalculationResult,
    calculate_selected_score,
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
