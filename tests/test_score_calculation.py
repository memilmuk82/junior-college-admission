from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from app.services.score_calculation import ScoreCalculationError, calculate_selected_score
from app.services.score_rule_schema import ScoreRuleDefinition
from app.services.score_selection import ScoreSelectionResult, select_terms_and_subjects
from tests.test_score_selection import _definition, _selection, _values


def _selected(
    definition: ScoreRuleDefinition | None = None,
) -> tuple[ScoreSelectionResult, ScoreRuleDefinition]:
    effective = definition or _definition()
    return select_terms_and_subjects(_selection(), effective, _values()), effective


def test_equal_weight_calculation_is_decimal_and_reproducible() -> None:
    selection, definition = _selected()

    first = calculate_selected_score(selection, definition)
    second = calculate_selected_score(selection, definition)

    assert first.final_score == Decimal("74.00")
    assert first == second


def test_grade_weights_apply_after_semester_selection() -> None:
    definition = replace(
        _definition(),
        grade_weight_1=Decimal("0.30"),
        grade_weight_2=Decimal("0.30"),
        grade_weight_3=Decimal("0.40"),
    )
    selection, definition = _selected(definition)

    result = calculate_selected_score(selection, definition)

    assert result.final_score == Decimal("74.25")
    assert result.trace.weighting_mode == "GRADE"


def test_semester_weights_apply_to_exact_selected_terms() -> None:
    definition = replace(
        _definition(),
        semester_weight_1_1=Decimal("0.10"),
        semester_weight_1_2=Decimal("0.10"),
        semester_weight_2_1=Decimal("0.20"),
        semester_weight_2_2=Decimal("0.30"),
        semester_weight_3_1=Decimal("0.30"),
    )
    selection, definition = _selected(definition)

    result = calculate_selected_score(selection, definition)

    assert result.final_score == Decimal("75.50")
    assert result.trace.weighting_mode == "SEMESTER"


def test_missing_or_conflicting_weight_is_never_guessed() -> None:
    definition = replace(
        _definition(),
        semester_weight_1_1=Decimal("0.50"),
        semester_weight_1_2=Decimal("0.50"),
    )
    selection, definition = _selected(definition)

    with pytest.raises(ScoreCalculationError):
        calculate_selected_score(selection, definition)


def test_rounding_modes_are_applied_only_at_declared_final_stage() -> None:
    definition = replace(_definition(), rounding_scale=1, rounding_mode="ROUND_DOWN")
    values = _values()
    values["course-1-1-a"] = replace(values["course-1-1-a"], normalized_value=Decimal("60.19"))
    selection = select_terms_and_subjects(_selection(), definition, values)

    result = calculate_selected_score(selection, definition)

    assert result.final_score == result.pre_round_score.quantize(
        Decimal("0.1"), rounding="ROUND_DOWN"
    )


def test_interview_and_practical_ratios_do_not_change_predicted_score() -> None:
    selection, definition = _selected()
    with_components = replace(
        definition,
        interview_ratio=Decimal("0.20"),
        practical_ratio=Decimal("0.30"),
    )

    base = calculate_selected_score(selection, definition)
    informational = calculate_selected_score(selection, with_components)

    assert informational.final_score == base.final_score
    assert informational.trace.non_predictive_components == (
        ("interview_ratio", Decimal("0.20")),
        ("practical_ratio", Decimal("0.30")),
    )
