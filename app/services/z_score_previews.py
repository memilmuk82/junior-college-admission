from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


@dataclass(frozen=True, slots=True)
class ZScorePreview:
    status: str
    raw_z_score: Decimal | None
    rounded_z_score: Decimal | None
    message: str


def build_z_score_previews(
    values: tuple[dict[str, str], ...],
) -> tuple[ZScorePreview, ...]:
    return tuple(_preview(row) for row in values)


def _preview(row: dict[str, str]) -> ZScorePreview:
    raw_values = (
        row.get("raw_score", "").strip(),
        row.get("course_mean", "").strip(),
        row.get("standard_deviation", "").strip(),
    )
    if not any(raw_values):
        return ZScorePreview("NOT_REQUESTED", None, None, "Z점수 입력 없음")
    if not all(raw_values):
        return ZScorePreview(
            "NEEDS_REVIEW",
            None,
            None,
            "원점수·평균·표준편차가 모두 있어야 합니다.",
        )
    try:
        raw_score, course_mean, standard_deviation = (Decimal(value) for value in raw_values)
    except InvalidOperation:
        return ZScorePreview("NEEDS_REVIEW", None, None, "숫자 입력을 확인하세요.")
    if not all(value.is_finite() for value in (raw_score, course_mean, standard_deviation)):
        return ZScorePreview("NEEDS_REVIEW", None, None, "유한한 숫자가 필요합니다.")
    if standard_deviation <= 0:
        return ZScorePreview("NEEDS_REVIEW", None, None, "표준편차는 0보다 커야 합니다.")
    raw_z_score = (raw_score - course_mean) / standard_deviation
    rounded = raw_z_score.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return ZScorePreview(
        "RAW_Z_READY",
        raw_z_score,
        rounded,
        "원시 Z=(원점수-평균)/표준편차. 대학별 공식 변환표는 계산 단계에서만 적용합니다.",
    )


__all__ = ["ZScorePreview", "build_z_score_previews"]
