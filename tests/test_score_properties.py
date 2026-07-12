from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.services.score_calculation import ScoreCalculationResult, calculate_selected_score
from app.services.score_selection import ComparableCourseValue, select_terms_and_subjects
from tests.test_score_selection import _definition, _selection

TERM_KEYS = ((1, 1), (1, 2), (2, 1), (2, 2), (3, 1))
GRADE_VALUES = st.lists(
    st.decimals(
        min_value=Decimal("1"),
        max_value=Decimal("9"),
        allow_nan=False,
        allow_infinity=False,
        places=2,
    ),
    min_size=10,
    max_size=10,
)


def _values(values: list[Decimal]) -> dict[str, ComparableCourseValue]:
    output: dict[str, ComparableCourseValue] = {}
    for (grade, semester), first, second in zip(TERM_KEYS, values[::2], values[1::2], strict=True):
        for suffix, value in (("a", first), ("b", second)):
            course_id = f"course-{grade}-{semester}-{suffix}"
            output[course_id] = ComparableCourseValue(
                course_record_id=course_id,
                normalized_value=value,
                value_scale="SYNTHETIC_GRADE",
                scope_codes=frozenset({"GENERAL_SUBJECTS"}),
            )
    return output


def _calculate(values: list[Decimal], *, reverse_records: bool = False) -> ScoreCalculationResult:
    definition = replace(
        _definition(),
        value_direction="LOWER_IS_BETTER",
        semester_selection_method="BEST_N",
        best_semester_count=2,
        rounding_stage="DISPLAY_ONLY",
        rounding_scale=None,
        display_scale=6,
    )
    selection = _selection()
    if reverse_records:
        selection = replace(selection, records=tuple(reversed(selection.records)))
    selected = select_terms_and_subjects(selection, definition, _values(values))
    return calculate_selected_score(
        selected,
        definition,
        rule_id="synthetic-property-rule",
        rule_version="synthetic-v1",
    )


@settings(max_examples=100, deadline=None)
@given(GRADE_VALUES)
def test_score_is_deterministic_and_input_order_independent(values: list[Decimal]) -> None:
    first = _calculate(values)
    repeated = _calculate(values)
    reversed_records = _calculate(values, reverse_records=True)

    assert first == repeated
    assert first == reversed_records
    assert Decimal(0) <= first.final_score <= first.maximum_score


@settings(max_examples=100, deadline=None)
@given(GRADE_VALUES)
def test_worsening_one_rank_grade_cannot_improve_lower_is_better_result(
    values: list[Decimal],
) -> None:
    base = _calculate(values)
    worsened = list(values)
    worsened[0] = min(Decimal("9"), worsened[0] + Decimal("0.25"))
    changed = _calculate(worsened)

    assert changed.final_score >= base.final_score
