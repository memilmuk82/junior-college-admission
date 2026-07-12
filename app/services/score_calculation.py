from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
)

from app.services.score_components import AttendanceScoreResult
from app.services.score_inputs import ScoreInputStatus
from app.services.score_rule_schema import ScoreRuleDefinition
from app.services.score_selection import ScoreSelectionResult, SelectedSemesterTrace


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
    rule_id: str
    rule_version: str
    weighting_mode: str
    grade_rounding_mode: str | None
    grade_rounding_scale: int | None
    components: tuple[WeightedComponentTrace, ...]
    aggregate_value: Decimal
    score_transform_mode: str
    score_base: Decimal | None
    score_multiplier: Decimal | None
    rounding_mode: str
    rounding_stage: str
    rounding_scale: int | None
    display_scale: int | None
    academic_score: Decimal
    attendance_score: Decimal | None
    attendance_maximum_score: Decimal | None
    attendance_table_code: str | None
    attendance_table_version: str | None
    non_predictive_components: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True)
class ScoreCalculationResult:
    pre_round_score: Decimal
    final_score: Decimal
    display_score: Decimal
    maximum_score: Decimal
    trace: ScoreCalculationTrace


def calculate_selected_score(
    selection: ScoreSelectionResult,
    definition: ScoreRuleDefinition,
    *,
    rule_id: str,
    rule_version: str,
    attendance: AttendanceScoreResult | None = None,
) -> ScoreCalculationResult:
    if not rule_id or not rule_version:
        raise ScoreCalculationError("계산 trace에 규칙 ID와 버전이 필요합니다.")
    if selection.status is not ScoreInputStatus.READY:
        raise ScoreCalculationError("READY 상태의 선택 결과만 계산할 수 있습니다.")
    if not selection.trace.selected_semesters:
        raise ScoreCalculationError("선택된 학기 비교값이 없습니다.")
    maximum_score = definition.maximum_score
    if maximum_score is None or maximum_score <= 0:
        raise ScoreCalculationError("양의 maximum_score가 필요합니다.")
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
    mode = definition.weighting_mode
    if mode == "GRADE_ONLY":
        _reject_present_weights(semester_weights.values(), "GRADE_ONLY 학기")
        components = _grade_components(
            selection,
            grade_weights,
            definition.grade_rounding_mode,
            definition.grade_rounding_scale,
        )
    elif mode == "GLOBAL_SEMESTER":
        _reject_present_weights(grade_weights.values(), "GLOBAL_SEMESTER 학년")
        components = _semester_components(selection, semester_weights)
    elif mode == "GRADE_WITHIN_SEMESTER":
        components = _grade_within_semester_components(selection, grade_weights, semester_weights)
    elif mode == "EQUAL":
        _reject_present_weights(grade_weights.values(), "EQUAL 학년")
        _reject_present_weights(semester_weights.values(), "EQUAL 학기")
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
    else:
        raise ScoreCalculationError(f"허용되지 않은 weighting_mode입니다: {mode}")

    aggregate_value = sum((component.contribution for component in components), Decimal(0))
    academic_score = _transform_score(aggregate_value, definition)
    if definition.attendance_included is True and attendance is None:
        raise ScoreCalculationError("출결 반영 규칙에는 검증된 출결 계산 결과가 필요합니다.")
    if definition.attendance_included is not True and attendance is not None:
        raise ScoreCalculationError("출결 미반영 규칙에 출결 점수를 합산할 수 없습니다.")
    if attendance is not None and (
        definition.attendance_table_code != attendance.trace.table_code
        or definition.attendance_source != attendance.trace.source
        or definition.attendance_minor_event_conversion_unit
        != attendance.trace.minor_event_conversion_unit
    ):
        raise ScoreCalculationError("출결 계산 결과가 현재 규칙의 표·출처·환산 단위와 다릅니다.")
    pre_round = academic_score + (attendance.score if attendance is not None else Decimal(0))
    if not Decimal(0) <= pre_round <= maximum_score:
        raise ScoreCalculationError("계산 결과가 0과 maximum_score 범위를 벗어났습니다.")
    final_score, display_score = _apply_rounding(pre_round, definition)
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
        display_score=display_score,
        maximum_score=maximum_score,
        trace=ScoreCalculationTrace(
            rule_id=rule_id,
            rule_version=rule_version,
            weighting_mode=mode,
            grade_rounding_mode=definition.grade_rounding_mode,
            grade_rounding_scale=definition.grade_rounding_scale,
            components=components,
            aggregate_value=aggregate_value,
            score_transform_mode=definition.score_transform_mode,
            score_base=definition.score_base,
            score_multiplier=definition.score_multiplier,
            rounding_mode=definition.rounding_mode,
            rounding_stage=definition.rounding_stage,
            rounding_scale=definition.rounding_scale,
            display_scale=definition.display_scale,
            academic_score=academic_score,
            attendance_score=None if attendance is None else attendance.score,
            attendance_maximum_score=(None if attendance is None else attendance.maximum_score),
            attendance_table_code=(None if attendance is None else attendance.trace.table_code),
            attendance_table_version=(
                None if attendance is None else attendance.trace.table_version
            ),
            non_predictive_components=non_predictive,
        ),
    )


def _grade_components(
    selection: ScoreSelectionResult,
    weights: dict[int, Decimal | None],
    rounding_mode: str | None,
    rounding_scale: int | None,
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
            _round_intermediate(
                sum(values, Decimal(0)) / Decimal(len(values)),
                rounding_mode,
                rounding_scale,
                "학년 평균",
            ),
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


def _grade_within_semester_components(
    selection: ScoreSelectionResult,
    grade_weights: dict[int, Decimal | None],
    semester_weights: dict[tuple[int, int], Decimal | None],
) -> tuple[WeightedComponentTrace, ...]:
    by_grade: dict[int, list[SelectedSemesterTrace]] = {}
    for term in selection.trace.selected_semesters:
        by_grade.setdefault(term.grade, []).append(term)
    selected_grade_weights = {grade: grade_weights[grade] for grade in by_grade}
    if any(value is None for value in selected_grade_weights.values()):
        raise ScoreCalculationError("선택된 학년의 가중치가 누락되었습니다.")
    if any(
        weight not in {None, Decimal(0)} and grade not in by_grade
        for grade, weight in grade_weights.items()
    ):
        raise ScoreCalculationError("성적이 없는 학년에 양의 가중치가 지정되었습니다.")
    if sum(
        (weight for weight in selected_grade_weights.values() if weight is not None),
        Decimal(0),
    ) != Decimal(1):
        raise ScoreCalculationError("선택된 학년 가중치 합계는 1이어야 합니다.")

    components: list[WeightedComponentTrace] = []
    selected_keys: set[tuple[int, int]] = set()
    for grade in sorted(by_grade):
        grade_weight = selected_grade_weights[grade]
        if grade_weight is None:
            raise ScoreCalculationError("선택된 학년의 가중치가 누락되었습니다.")
        terms = by_grade[grade]
        local_weights: list[Decimal] = []
        for term in terms:
            key = (term.grade, term.semester)
            selected_keys.add(key)
            local_weight = semester_weights[key]
            if local_weight is None:
                raise ScoreCalculationError("선택된 학년 내부 학기 가중치가 누락되었습니다.")
            local_weights.append(local_weight)
            effective_weight = grade_weight * local_weight
            components.append(
                WeightedComponentTrace(
                    key=f"grade_{term.grade}_semester_{term.semester}",
                    value=term.comparison_value,
                    weight=effective_weight,
                    contribution=term.comparison_value * effective_weight,
                )
            )
        if sum(local_weights, Decimal(0)) != Decimal(1):
            raise ScoreCalculationError(f"{grade}학년 내부 학기 가중치 합계는 1이어야 합니다.")
    if any(
        weight not in {None, Decimal(0)} and key not in selected_keys
        for key, weight in semester_weights.items()
    ):
        raise ScoreCalculationError("선택되지 않은 학기에 양의 내부 가중치가 지정되었습니다.")
    return tuple(components)


def _component(key: str, value: Decimal, weight: Decimal | None) -> WeightedComponentTrace:
    if weight is None:
        raise ScoreCalculationError("가중치가 누락되었습니다.")
    return WeightedComponentTrace(
        key=key,
        value=value,
        weight=weight,
        contribution=value * weight,
    )


def _reject_present_weights(values: Iterable[Decimal | None], label: str) -> None:
    if any(value is not None for value in values):
        raise ScoreCalculationError(f"{label} 가중치는 입력할 수 없습니다.")


def _apply_rounding(value: Decimal, definition: ScoreRuleDefinition) -> tuple[Decimal, Decimal]:
    if definition.rounding_stage == "FINAL":
        if definition.rounding_scale is None:
            raise ScoreCalculationError("FINAL 반올림에는 rounding_scale이 필요합니다.")
        final = _round_score(value, definition.rounding_mode, definition.rounding_scale)
        display_scale = definition.display_scale
        displayed = (
            final
            if display_scale is None
            else _round_score(final, definition.rounding_mode, display_scale)
        )
        return final, displayed
    if definition.rounding_stage == "DISPLAY_ONLY":
        if definition.display_scale is None:
            raise ScoreCalculationError("DISPLAY_ONLY에는 display_scale이 필요합니다.")
        return value, _round_score(value, definition.rounding_mode, definition.display_scale)
    if definition.rounding_stage == "MANUAL_REVIEW":
        raise ScoreCalculationError("MANUAL_REVIEW 반올림 단계는 자동 계산할 수 없습니다.")
    raise ScoreCalculationError(f"허용되지 않은 rounding_stage입니다: {definition.rounding_stage}")


def _transform_score(value: Decimal, definition: ScoreRuleDefinition) -> Decimal:
    if definition.score_transform_mode == "IDENTITY":
        if definition.score_base is not None or definition.score_multiplier is not None:
            raise ScoreCalculationError("IDENTITY에는 변환 상수와 배수를 입력할 수 없습니다.")
        return value
    if definition.score_transform_mode == "LINEAR":
        if definition.score_base is None or definition.score_multiplier is None:
            raise ScoreCalculationError("LINEAR에는 변환 상수와 배수가 필요합니다.")
        return definition.score_base + definition.score_multiplier * value
    if definition.score_transform_mode == "MANUAL_REVIEW":
        raise ScoreCalculationError("MANUAL_REVIEW 점수 변환은 자동 계산할 수 없습니다.")
    raise ScoreCalculationError(
        f"허용되지 않은 score_transform_mode입니다: {definition.score_transform_mode}"
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


def _round_intermediate(
    value: Decimal,
    mode: str | None,
    scale: int | None,
    label: str,
) -> Decimal:
    if mode is None and scale is None:
        return value
    if mode is None or scale is None:
        raise ScoreCalculationError(f"{label} 반올림에는 mode와 scale이 모두 필요합니다.")
    return _round_score(value, mode, scale)


__all__ = [
    "ScoreCalculationError",
    "ScoreCalculationResult",
    "ScoreCalculationTrace",
    "WeightedComponentTrace",
    "calculate_selected_score",
]
