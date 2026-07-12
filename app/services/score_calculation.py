from __future__ import annotations

from dataclasses import dataclass
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
)

from app.services.score_inputs import ScoreInputStatus
from app.services.score_rule_schema import ScoreRuleDefinition
from app.services.score_selection import ScoreSelectionResult


class ScoreCalculationError(ValueError):
    pass


@dataclass(frozen=True)
class WeightedComponentTrace:
    key: str
    value: Decimal
    weight: Decimal
    contribution: Decimal


@dataclass(frozen=True)
class ScoreCalculationTrace:
    weighting_mode: str
    components: tuple[WeightedComponentTrace, ...]
    rounding_mode: str
    rounding_scale: int
    non_predictive_components: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True)
class ScoreCalculationResult:
    pre_round_score: Decimal
    final_score: Decimal
    maximum_score: Decimal
    trace: ScoreCalculationTrace


def calculate_selected_score(
    selection: ScoreSelectionResult,
    definition: ScoreRuleDefinition,
) -> ScoreCalculationResult:
    if selection.status is not ScoreInputStatus.READY:
        raise ScoreCalculationError("READY 상태의 선택 결과만 계산할 수 있습니다.")
    if not selection.trace.selected_semesters:
        raise ScoreCalculationError("선택된 학기 비교값이 없습니다.")
    maximum_score = definition.maximum_score
    if maximum_score is None or maximum_score <= 0:
        raise ScoreCalculationError("양의 maximum_score가 필요합니다.")
    if definition.rounding_scale is None:
        raise ScoreCalculationError("rounding_scale이 필요합니다.")

    grade_weights = {
        1: definition.grade_weight_1,
        2: definition.grade_weight_2,
        3: definition.grade_weight_3,
    }
    semester_weights = {
        (1, 1): definition.semester_weight_1_1,
        (1, 2): definition.semester_weight_1_2,
        (2, 1): definition.semester_weight_2_1,
        (2, 2): definition.semester_weight_2_2,
        (3, 1): definition.semester_weight_3_1,
        (3, 2): definition.semester_weight_3_2,
    }
    has_grade_weights = any(value is not None for value in grade_weights.values())
    has_semester_weights = any(value is not None for value in semester_weights.values())
    if has_grade_weights and has_semester_weights:
        raise ScoreCalculationError("학년 가중치와 학기 가중치를 동시에 적용할 수 없습니다.")

    if has_grade_weights:
        mode = "GRADE"
        components = _grade_components(selection, grade_weights)
    elif has_semester_weights:
        mode = "SEMESTER"
        components = _semester_components(selection, semester_weights)
    else:
        mode = "EQUAL"
        count = Decimal(len(selection.trace.selected_semesters))
        weight = Decimal(1) / count
        components = tuple(
            WeightedComponentTrace(
                key=f"grade_{term.grade}_semester_{term.semester}",
                value=term.comparison_value,
                weight=weight,
                contribution=term.comparison_value * weight,
            )
            for term in selection.trace.selected_semesters
        )

    pre_round = sum((component.contribution for component in components), Decimal(0))
    if not Decimal(0) <= pre_round <= maximum_score:
        raise ScoreCalculationError("계산 결과가 0과 maximum_score 범위를 벗어났습니다.")
    final_score = _round_score(pre_round, definition.rounding_mode, definition.rounding_scale)
    non_predictive = tuple(
        (name, value)
        for name, value in (
            ("interview_ratio", definition.interview_ratio),
            ("practical_ratio", definition.practical_ratio),
        )
        if value is not None
    )
    return ScoreCalculationResult(
        pre_round_score=pre_round,
        final_score=final_score,
        maximum_score=maximum_score,
        trace=ScoreCalculationTrace(
            weighting_mode=mode,
            components=components,
            rounding_mode=definition.rounding_mode,
            rounding_scale=definition.rounding_scale,
            non_predictive_components=non_predictive,
        ),
    )


def _grade_components(
    selection: ScoreSelectionResult,
    weights: dict[int, Decimal | None],
) -> tuple[WeightedComponentTrace, ...]:
    by_grade: dict[int, list[Decimal]] = {}
    for term in selection.trace.selected_semesters:
        by_grade.setdefault(term.grade, []).append(term.comparison_value)
    selected_weights = {grade: weights[grade] for grade in by_grade}
    if any(value is None for value in selected_weights.values()):
        raise ScoreCalculationError("선택된 학년의 가중치가 누락되었습니다.")
    if any(
        weight not in {None, Decimal(0)} and grade not in by_grade
        for grade, weight in weights.items()
    ):
        raise ScoreCalculationError("성적이 없는 학년에 양의 가중치가 지정되었습니다.")
    if sum(
        (weight for weight in selected_weights.values() if weight is not None),
        Decimal(0),
    ) != Decimal(1):
        raise ScoreCalculationError("선택된 학년 가중치 합계는 1이어야 합니다.")
    return tuple(
        _component(
            f"grade_{grade}",
            sum(values, Decimal(0)) / Decimal(len(values)),
            selected_weights[grade],
        )
        for grade, values in sorted(by_grade.items())
    )


def _semester_components(
    selection: ScoreSelectionResult,
    weights: dict[tuple[int, int], Decimal | None],
) -> tuple[WeightedComponentTrace, ...]:
    selected_terms = {
        (term.grade, term.semester): term for term in selection.trace.selected_semesters
    }
    if len(selected_terms) != len(selection.trace.selected_semesters):
        raise ScoreCalculationError("같은 학년·학기 성적이 둘 이상 선택되었습니다.")
    selected_weights = tuple(weights[key] for key in selected_terms)
    if any(weight is None for weight in selected_weights):
        raise ScoreCalculationError("선택된 학기의 가중치가 누락되었습니다.")
    if any(
        weight not in {None, Decimal(0)} and key not in selected_terms
        for key, weight in weights.items()
    ):
        raise ScoreCalculationError("선택되지 않은 학기에 양의 가중치가 지정되었습니다.")
    if sum(
        (weight for weight in selected_weights if weight is not None),
        Decimal(0),
    ) != Decimal(1):
        raise ScoreCalculationError("선택된 학기 가중치 합계는 1이어야 합니다.")
    return tuple(
        _component(
            f"grade_{key[0]}_semester_{key[1]}",
            selected_terms[key].comparison_value,
            weights[key],
        )
        for key in sorted(selected_terms)
    )


def _component(key: str, value: Decimal, weight: Decimal | None) -> WeightedComponentTrace:
    if weight is None:
        raise ScoreCalculationError("가중치가 누락되었습니다.")
    return WeightedComponentTrace(
        key=key,
        value=value,
        weight=weight,
        contribution=value * weight,
    )


def _round_score(value: Decimal, mode: str, scale: int) -> Decimal:
    modes = {
        "ROUND_HALF_UP": ROUND_HALF_UP,
        "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
        "ROUND_DOWN": ROUND_DOWN,
        "ROUND_UP": ROUND_UP,
        "TRUNCATE": ROUND_DOWN,
    }
    if mode == "MANUAL_REVIEW":
        raise ScoreCalculationError("MANUAL_REVIEW 반올림 규칙은 자동 계산할 수 없습니다.")
    try:
        decimal_mode = modes[mode]
    except KeyError as error:
        raise ScoreCalculationError(f"허용되지 않은 반올림 방식입니다: {mode}") from error
    quantum = Decimal(1).scaleb(-scale)
    return value.quantize(quantum, rounding=decimal_mode)


__all__ = [
    "ScoreCalculationError",
    "ScoreCalculationResult",
    "ScoreCalculationTrace",
    "WeightedComponentTrace",
    "calculate_selected_score",
]
