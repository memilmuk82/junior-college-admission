from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, ROUND_UP, Decimal

from app.services.score_rule_schema import Z_SCORE_SOURCES, ScoreRuleDefinition, ZScoreTableRow


class ScoreConversionError(ValueError):
    pass


@dataclass(frozen=True)
class ZScoreConversionTrace:
    formula_version: str
    raw_z_score: Decimal
    rounded_z_score: Decimal
    applied_z_score: Decimal
    rounding_mode: str
    rounding_scale: int
    clip_min: Decimal | None
    clip_max: Decimal | None
    source: str
    official: bool
    table_code: str
    table_version: str
    evidence_document_id: str
    evidence_page: int
    evidence_location: str
    source_status: str


@dataclass(frozen=True)
class ZScoreConversionResult:
    converted_value: Decimal
    trace: ZScoreConversionTrace


def convert_z_score_for_rule(
    *,
    raw_score: Decimal | None,
    course_mean: Decimal | None,
    standard_deviation: Decimal | None,
    definition: ScoreRuleDefinition,
    table_rows: tuple[ZScoreTableRow, ...],
    table_version: str,
) -> ZScoreConversionResult:
    if definition.z_score_policy != "TABLE_LOOKUP":
        raise ScoreConversionError("TABLE_LOOKUP Z점수 규칙만 변환표 계산을 실행할 수 있습니다.")
    if (
        definition.z_score_table_code is None
        or definition.z_score_source is None
        or definition.z_score_rounding_mode is None
        or definition.z_score_rounding_scale is None
    ):
        raise ScoreConversionError("Z점수 규칙의 출처·표·반올림 설정이 누락되었습니다.")
    if definition.z_score_formula_version != "STANDARD_Z_V1":
        raise ScoreConversionError("지원하지 않는 Z점수 공식 버전입니다.")
    return convert_z_score(
        raw_score=raw_score,
        course_mean=course_mean,
        standard_deviation=standard_deviation,
        table_rows=table_rows,
        table_code=definition.z_score_table_code,
        table_version=table_version,
        source=definition.z_score_source,
        rounding_mode=definition.z_score_rounding_mode,
        rounding_scale=definition.z_score_rounding_scale,
        clip_min=definition.z_score_clip_min,
        clip_max=definition.z_score_clip_max,
    )


def convert_z_score(
    *,
    raw_score: Decimal | None,
    course_mean: Decimal | None,
    standard_deviation: Decimal | None,
    table_rows: tuple[ZScoreTableRow, ...],
    table_code: str,
    table_version: str,
    source: str,
    rounding_mode: str,
    rounding_scale: int,
    clip_min: Decimal | None,
    clip_max: Decimal | None,
) -> ZScoreConversionResult:
    if raw_score is None or course_mean is None or standard_deviation is None:
        raise ScoreConversionError("Z점수 계산에 원점수·과목평균·표준편차가 모두 필요합니다.")
    if not all(value.is_finite() for value in (raw_score, course_mean, standard_deviation)):
        raise ScoreConversionError("Z점수 입력은 유한한 Decimal이어야 합니다.")
    if standard_deviation <= 0:
        raise ScoreConversionError("표준편차는 0보다 커야 하며 임의 값으로 대체할 수 없습니다.")
    if source not in Z_SCORE_SOURCES or source == "MANUAL_REVIEW":
        raise ScoreConversionError("검수 가능한 Z점수 출처 코드가 필요합니다.")
    if not table_code or not table_version:
        raise ScoreConversionError("Z점수 변환표 코드와 버전이 필요합니다.")
    if (clip_min is None) != (clip_max is None):
        raise ScoreConversionError("Z점수 절단 하한과 상한은 함께 지정해야 합니다.")
    if clip_min is not None and clip_max is not None and clip_min >= clip_max:
        raise ScoreConversionError("Z점수 절단 하한은 상한보다 작아야 합니다.")

    raw_z_score = (raw_score - course_mean) / standard_deviation
    rounded_z_score = _round_decimal(raw_z_score, rounding_mode, rounding_scale)
    applied_z_score = rounded_z_score
    if clip_min is not None and applied_z_score < clip_min:
        applied_z_score = clip_min
    if clip_max is not None and applied_z_score > clip_max:
        applied_z_score = clip_max

    candidates = tuple(
        row
        for row in table_rows
        if row.table_code == table_code and _contains(row, applied_z_score)
    )
    if len(candidates) != 1:
        raise ScoreConversionError("Z점수가 변환표의 정확히 한 구간과 일치해야 합니다.")
    row = candidates[0]
    official = source == "UNIVERSITY_OFFICIAL"
    official_statuses = {
        "AMENDED_FINAL_GUIDE",
        "FINAL_GUIDE",
        "AMENDED_IMPLEMENTATION_PLAN",
        "IMPLEMENTATION_PLAN",
    }
    if official and row.source_status not in official_statuses:
        raise ScoreConversionError("참고 변환표를 UNIVERSITY_OFFICIAL로 표시할 수 없습니다.")
    return ZScoreConversionResult(
        converted_value=row.converted_value,
        trace=ZScoreConversionTrace(
            formula_version="STANDARD_Z_V1",
            raw_z_score=raw_z_score,
            rounded_z_score=rounded_z_score,
            applied_z_score=applied_z_score,
            rounding_mode=rounding_mode,
            rounding_scale=rounding_scale,
            clip_min=clip_min,
            clip_max=clip_max,
            source=source,
            official=official,
            table_code=table_code,
            table_version=table_version,
            evidence_document_id=row.evidence_document_id,
            evidence_page=row.evidence_page,
            evidence_location=row.evidence_location,
            source_status=row.source_status,
        ),
    )


def _contains(row: ZScoreTableRow, value: Decimal) -> bool:
    lower_matches = (
        row.z_min is None or value > row.z_min or (row.z_min_inclusive and value == row.z_min)
    )
    upper_matches = (
        row.z_max is None or value < row.z_max or (row.z_max_inclusive and value == row.z_max)
    )
    return lower_matches and upper_matches


def _round_decimal(value: Decimal, mode: str, scale: int) -> Decimal:
    modes = {
        "ROUND_HALF_UP": ROUND_HALF_UP,
        "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
        "ROUND_DOWN": ROUND_DOWN,
        "ROUND_UP": ROUND_UP,
        "TRUNCATE": ROUND_DOWN,
    }
    if not 0 <= scale <= 12:
        raise ScoreConversionError("Z점수 반올림 자릿수는 0~12여야 합니다.")
    try:
        decimal_mode = modes[mode]
    except KeyError as error:
        raise ScoreConversionError(f"허용되지 않은 Z점수 반올림 방식입니다: {mode}") from error
    return value.quantize(Decimal(1).scaleb(-scale), rounding=decimal_mode)


__all__ = [
    "ScoreConversionError",
    "ZScoreConversionResult",
    "ZScoreConversionTrace",
    "convert_z_score",
    "convert_z_score_for_rule",
]
