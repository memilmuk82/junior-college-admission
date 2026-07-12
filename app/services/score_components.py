from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from app.services.score_rule_schema import Z_SCORE_SOURCES


class ScoreComponentError(ValueError):
    pass


class AchievementConversionError(ScoreComponentError):
    pass


@dataclass(frozen=True)
class AchievementTableRow:
    table_code: str
    achievement_level: str
    distribution_key: str | None
    distribution_min: Decimal | None
    distribution_min_inclusive: bool
    distribution_max: Decimal | None
    distribution_max_inclusive: bool
    converted_value: Decimal
    evidence_document_id: str
    evidence_page: int
    evidence_location: str
    source_status: str


@dataclass(frozen=True)
class AchievementConversionTrace:
    handling: str
    achievement_level: str
    distribution_scale: str | None
    distribution_key: str | None
    distribution_value: Decimal | None
    source: str
    official: bool
    table_code: str
    table_version: str
    evidence_document_id: str
    evidence_page: int
    evidence_location: str
    source_status: str


@dataclass(frozen=True)
class AchievementConversionResult:
    converted_value: Decimal
    trace: AchievementConversionTrace


@dataclass(frozen=True)
class AttendanceInput:
    unexcused_absence_days: int | None
    unexcused_late_count: int | None
    unexcused_early_leave_count: int | None
    unexcused_class_absence_count: int | None
    verified: bool


@dataclass(frozen=True)
class AttendanceTableRow:
    table_code: str
    absence_min: int
    absence_max: int | None
    score: Decimal
    maximum_score: Decimal
    evidence_document_id: str
    evidence_page: int
    evidence_location: str
    source_status: str


@dataclass(frozen=True)
class AttendanceConversionTrace:
    equivalent_absence_days: int
    minor_event_total: int
    minor_event_conversion_unit: int
    minor_event_remainder: int
    source: str
    official: bool
    table_code: str
    table_version: str
    evidence_document_id: str
    evidence_page: int
    evidence_location: str
    source_status: str


@dataclass(frozen=True)
class AttendanceScoreResult:
    score: Decimal
    maximum_score: Decimal
    trace: AttendanceConversionTrace


def convert_achievement(
    *,
    achievement_level: str | None,
    achievement_distribution: Mapping[str, Decimal] | None,
    raw_score_label: str | None,
    handling: str,
    formula_version: str,
    distribution_scale: str | None,
    table_rows: tuple[AchievementTableRow, ...],
    table_code: str,
    table_version: str,
    source: str,
) -> AchievementConversionResult:
    if raw_score_label == "P":
        raise AchievementConversionError("P는 숫자 성취도나 0으로 변환할 수 없습니다.")
    if achievement_level is None or not achievement_level.strip():
        raise AchievementConversionError("성취도 값이 누락되었습니다.")
    if handling not in {"GRADE_TABLE", "DISTRIBUTION"}:
        raise AchievementConversionError("자동 계산 가능한 성취도 처리 방식이 아닙니다.")
    try:
        _validate_source(source, table_code, table_version)
    except ScoreComponentError as error:
        raise AchievementConversionError(str(error)) from error

    distribution_key: str | None = None
    distribution_value: Decimal | None = None
    if handling == "GRADE_TABLE":
        if formula_version != "TABLE_LOOKUP_V1":
            raise AchievementConversionError("GRADE_TABLE 공식 버전이 유효하지 않습니다.")
        if distribution_scale is not None:
            raise AchievementConversionError("GRADE_TABLE에는 분포 척도를 지정할 수 없습니다.")
        candidates = tuple(
            row
            for row in table_rows
            if row.table_code == table_code
            and row.achievement_level == achievement_level
            and row.distribution_key is None
            and row.distribution_min is None
            and row.distribution_max is None
        )
    elif formula_version == "TABLE_LOOKUP_V1":
        distribution = _validate_distribution(achievement_distribution, distribution_scale)
        candidates_list: list[AchievementTableRow] = []
        for row in table_rows:
            if (
                row.table_code != table_code
                or row.achievement_level != achievement_level
                or row.distribution_key is None
            ):
                continue
            value = distribution.get(row.distribution_key)
            if value is not None and _decimal_range_contains(row, value):
                candidates_list.append(row)
                distribution_key = row.distribution_key
                distribution_value = value
        candidates = tuple(candidates_list)
    elif formula_version == "CUMULATIVE_DISTRIBUTION_GRADE_V1":
        distribution = _validate_distribution(achievement_distribution, distribution_scale)
        return _convert_cumulative_distribution(
            achievement_level=achievement_level,
            distribution=distribution,
            table_rows=table_rows,
            table_code=table_code,
            table_version=table_version,
            source=source,
        )
    else:
        raise AchievementConversionError("지원하지 않는 성취도 공식 버전입니다.")

    if len(candidates) != 1:
        raise AchievementConversionError("성취도가 변환표의 정확히 한 행과 일치해야 합니다.")
    row = candidates[0]
    try:
        _validate_evidence_source(source, row.source_status)
    except ScoreComponentError as error:
        raise AchievementConversionError(str(error)) from error
    return AchievementConversionResult(
        converted_value=row.converted_value,
        trace=AchievementConversionTrace(
            handling=handling,
            achievement_level=achievement_level,
            distribution_scale=distribution_scale,
            distribution_key=distribution_key,
            distribution_value=distribution_value,
            source=source,
            official=source == "UNIVERSITY_OFFICIAL",
            table_code=table_code,
            table_version=table_version,
            evidence_document_id=row.evidence_document_id,
            evidence_page=row.evidence_page,
            evidence_location=row.evidence_location,
            source_status=row.source_status,
        ),
    )


def _convert_cumulative_distribution(
    *,
    achievement_level: str,
    distribution: dict[str, Decimal],
    table_rows: tuple[AchievementTableRow, ...],
    table_code: str,
    table_version: str,
    source: str,
) -> AchievementConversionResult:
    if achievement_level not in {"A", "B", "C"}:
        raise AchievementConversionError("누적분포 공식은 A·B·C 성취도만 지원합니다.")
    required: tuple[str, ...] = ("A",) if achievement_level == "A" else ("A", "B")
    if achievement_level == "C":
        required = ("A", "B", "C")
    if any(key not in distribution for key in required):
        raise AchievementConversionError("누적분포 계산에 필요한 성취도 비율이 누락되었습니다.")
    cumulative_current = sum((distribution[key] for key in required), Decimal(0))
    if achievement_level == "A":
        base_grade = Decimal(1)
        row = next(
            (row for row in table_rows if row.table_code == table_code),
            None,
        )
    else:
        prior_keys = ("A",) if achievement_level == "B" else ("A", "B")
        prior_cumulative = sum((distribution[key] for key in prior_keys), Decimal(0))
        candidates = tuple(
            row
            for row in table_rows
            if row.table_code == table_code
            and row.distribution_key == "CUMULATIVE"
            and _decimal_range_contains(row, prior_cumulative)
        )
        if len(candidates) != 1:
            raise AchievementConversionError(
                "누적분포가 등급표의 정확히 한 구간과 일치해야 합니다."
            )
        row = candidates[0]
        base_grade = row.converted_value
    if row is None:
        raise AchievementConversionError("누적분포 공식의 근거 표가 필요합니다.")
    _validate_evidence_source(source, row.source_status)
    return AchievementConversionResult(
        converted_value=base_grade + cumulative_current / Decimal(100),
        trace=AchievementConversionTrace(
            handling="DISTRIBUTION",
            achievement_level=achievement_level,
            distribution_scale="PERCENT",
            distribution_key="CUMULATIVE",
            distribution_value=cumulative_current,
            source=source,
            official=source == "UNIVERSITY_OFFICIAL",
            table_code=table_code,
            table_version=table_version,
            evidence_document_id=row.evidence_document_id,
            evidence_page=row.evidence_page,
            evidence_location=row.evidence_location,
            source_status=row.source_status,
        ),
    )


def convert_attendance(
    *,
    attendance: AttendanceInput,
    table_rows: tuple[AttendanceTableRow, ...],
    table_code: str,
    table_version: str,
    source: str,
    minor_event_conversion_unit: int,
) -> AttendanceScoreResult:
    _validate_source(source, table_code, table_version)
    if not attendance.verified:
        raise ScoreComponentError("검증되지 않은 출결은 계산할 수 없습니다.")
    counts = (
        attendance.unexcused_absence_days,
        attendance.unexcused_late_count,
        attendance.unexcused_early_leave_count,
        attendance.unexcused_class_absence_count,
    )
    if any(value is None for value in counts):
        raise ScoreComponentError("출결 누락값을 0으로 해석할 수 없습니다.")
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in counts
        if value is not None
    ):
        raise ScoreComponentError("출결 횟수는 0 이상의 정수여야 합니다.")
    if not isinstance(minor_event_conversion_unit, int) or minor_event_conversion_unit <= 0:
        raise ScoreComponentError("출결 환산 단위는 양의 정수여야 합니다.")

    absence_days = attendance.unexcused_absence_days
    if absence_days is None:
        raise ScoreComponentError("미인정 결석일이 누락되었습니다.")
    minor_total = sum(value for value in counts[1:] if value is not None)
    equivalent = absence_days + minor_total // minor_event_conversion_unit
    candidates = tuple(
        row
        for row in table_rows
        if row.table_code == table_code
        and equivalent >= row.absence_min
        and (row.absence_max is None or equivalent <= row.absence_max)
    )
    if len(candidates) != 1:
        raise ScoreComponentError("출결 환산일이 변환표의 정확히 한 행과 일치해야 합니다.")
    row = candidates[0]
    if not row.score.is_finite() or not row.maximum_score.is_finite():
        raise ScoreComponentError("출결 점수와 만점은 유한한 Decimal이어야 합니다.")
    if row.maximum_score <= 0 or not Decimal(0) <= row.score <= row.maximum_score:
        raise ScoreComponentError("출결 점수가 0과 출결 만점 범위를 벗어났습니다.")
    _validate_evidence_source(source, row.source_status)
    return AttendanceScoreResult(
        score=row.score,
        maximum_score=row.maximum_score,
        trace=AttendanceConversionTrace(
            equivalent_absence_days=equivalent,
            minor_event_total=minor_total,
            minor_event_conversion_unit=minor_event_conversion_unit,
            minor_event_remainder=minor_total % minor_event_conversion_unit,
            source=source,
            official=source == "UNIVERSITY_OFFICIAL",
            table_code=table_code,
            table_version=table_version,
            evidence_document_id=row.evidence_document_id,
            evidence_page=row.evidence_page,
            evidence_location=row.evidence_location,
            source_status=row.source_status,
        ),
    )


def _validate_distribution(
    distribution: Mapping[str, Decimal] | None, scale: str | None
) -> dict[str, Decimal]:
    if not distribution:
        raise AchievementConversionError("성취도 분포가 누락되었습니다.")
    expected_sum = {"RATIO": Decimal(1), "PERCENT": Decimal(100)}.get(scale or "")
    if expected_sum is None:
        raise AchievementConversionError("성취도 분포 척도는 RATIO 또는 PERCENT여야 합니다.")
    normalized = dict(distribution)
    if any(not key or not isinstance(value, Decimal) for key, value in normalized.items()):
        raise AchievementConversionError("성취도 분포는 코드별 Decimal이어야 합니다.")
    if any(not value.is_finite() or value < 0 for value in normalized.values()):
        raise AchievementConversionError("성취도 분포는 0 이상의 유한한 Decimal이어야 합니다.")
    if sum(normalized.values(), Decimal(0)) != expected_sum:
        raise AchievementConversionError("성취도 분포 합계가 선언된 척도와 일치해야 합니다.")
    return normalized


def _decimal_range_contains(row: AchievementTableRow, value: Decimal) -> bool:
    lower = (
        row.distribution_min is None
        or value > row.distribution_min
        or (row.distribution_min_inclusive and value == row.distribution_min)
    )
    upper = (
        row.distribution_max is None
        or value < row.distribution_max
        or (row.distribution_max_inclusive and value == row.distribution_max)
    )
    return lower and upper


def _validate_source(source: str, table_code: str, table_version: str) -> None:
    if source not in Z_SCORE_SOURCES or source == "MANUAL_REVIEW":
        raise ScoreComponentError("검수 가능한 출처 코드가 필요합니다.")
    if not table_code or not table_version:
        raise ScoreComponentError("변환표 코드와 버전이 필요합니다.")


def _validate_evidence_source(source: str, source_status: str) -> None:
    official_statuses = {
        "AMENDED_FINAL_GUIDE",
        "FINAL_GUIDE",
        "AMENDED_IMPLEMENTATION_PLAN",
        "IMPLEMENTATION_PLAN",
    }
    if source == "UNIVERSITY_OFFICIAL" and source_status not in official_statuses:
        raise ScoreComponentError("참고자료를 UNIVERSITY_OFFICIAL로 표시할 수 없습니다.")


__all__ = [
    "AchievementConversionError",
    "AchievementConversionResult",
    "AchievementConversionTrace",
    "AchievementTableRow",
    "AttendanceConversionTrace",
    "AttendanceInput",
    "AttendanceScoreResult",
    "AttendanceTableRow",
    "ScoreComponentError",
    "convert_achievement",
    "convert_attendance",
]
