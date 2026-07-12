from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.score_components import (
    AchievementConversionError,
    AchievementTableRow,
    AttendanceInput,
    AttendanceTableRow,
    ScoreComponentError,
    convert_achievement,
    convert_attendance,
)


def _achievement_row(
    value: str,
    *,
    level: str = "A",
    key: str | None = None,
    lower: str | None = None,
    upper: str | None = None,
    status: str = "FINAL_GUIDE",
) -> AchievementTableRow:
    return AchievementTableRow(
        table_code="SYNTHETIC_ACHIEVEMENT_V1",
        achievement_level=level,
        distribution_key=key,
        distribution_min=None if lower is None else Decimal(lower),
        distribution_min_inclusive=True,
        distribution_max=None if upper is None else Decimal(upper),
        distribution_max_inclusive=False,
        converted_value=Decimal(value),
        evidence_document_id="synthetic-guide",
        evidence_page=10,
        evidence_location="합성 성취도 표",
        source_status=status,
    )


def test_grade_table_conversion_is_versioned_and_deterministic() -> None:
    result = convert_achievement(
        achievement_level="A",
        achievement_distribution=None,
        raw_score_label=None,
        handling="GRADE_TABLE",
        distribution_scale=None,
        table_rows=(_achievement_row("1"), _achievement_row("3", level="B")),
        table_code="SYNTHETIC_ACHIEVEMENT_V1",
        table_version="synthetic-v1",
        source="UNIVERSITY_OFFICIAL",
    )

    assert result.converted_value == Decimal("1")
    assert result.trace.table_version == "synthetic-v1"
    assert result.trace.official is True


def test_distribution_conversion_keeps_missing_and_zero_distinct() -> None:
    rows = (
        _achievement_row("1", key="A", lower="0.50", upper=None),
        _achievement_row("3", key="A", lower="0", upper="0.50"),
    )
    converted = convert_achievement(
        achievement_level="A",
        achievement_distribution={"A": Decimal("0.60"), "B": Decimal("0.40")},
        raw_score_label=None,
        handling="DISTRIBUTION",
        distribution_scale="RATIO",
        table_rows=rows,
        table_code="SYNTHETIC_ACHIEVEMENT_V1",
        table_version="synthetic-v1",
        source="VERIFIED_REFERENCE",
    )

    assert converted.converted_value == Decimal("1")
    assert converted.trace.distribution_value == Decimal("0.60")

    with pytest.raises(AchievementConversionError):
        convert_achievement(
            achievement_level="A",
            achievement_distribution={"B": Decimal("1")},
            raw_score_label=None,
            handling="DISTRIBUTION",
            distribution_scale="RATIO",
            table_rows=rows,
            table_code="SYNTHETIC_ACHIEVEMENT_V1",
            table_version="synthetic-v1",
            source="VERIFIED_REFERENCE",
        )


def test_pass_label_and_reference_source_cannot_be_converted_as_official() -> None:
    with pytest.raises(AchievementConversionError):
        convert_achievement(
            achievement_level="P",
            achievement_distribution=None,
            raw_score_label="P",
            handling="GRADE_TABLE",
            distribution_scale=None,
            table_rows=(_achievement_row("1"),),
            table_code="SYNTHETIC_ACHIEVEMENT_V1",
            table_version="synthetic-v1",
            source="UNIVERSITY_OFFICIAL",
        )

    with pytest.raises(AchievementConversionError):
        convert_achievement(
            achievement_level="A",
            achievement_distribution=None,
            raw_score_label=None,
            handling="GRADE_TABLE",
            distribution_scale=None,
            table_rows=(_achievement_row("1", status="VERIFIED_REFERENCE"),),
            table_code="SYNTHETIC_ACHIEVEMENT_V1",
            table_version="synthetic-v1",
            source="UNIVERSITY_OFFICIAL",
        )


def _attendance_row(
    score: str,
    lower: int,
    upper: int | None,
    *,
    status: str = "FINAL_GUIDE",
) -> AttendanceTableRow:
    return AttendanceTableRow(
        table_code="SYNTHETIC_ATTENDANCE_V1",
        absence_min=lower,
        absence_max=upper,
        score=Decimal(score),
        maximum_score=Decimal("20"),
        evidence_document_id="synthetic-guide",
        evidence_page=11,
        evidence_location="합성 출결 표",
        source_status=status,
    )


def test_attendance_uses_only_verified_counts_and_explicit_conversion_unit() -> None:
    result = convert_attendance(
        attendance=AttendanceInput(
            unexcused_absence_days=1,
            unexcused_late_count=2,
            unexcused_early_leave_count=1,
            unexcused_class_absence_count=0,
            verified=True,
        ),
        table_rows=(_attendance_row("20", 0, 1), _attendance_row("18", 2, None)),
        table_code="SYNTHETIC_ATTENDANCE_V1",
        table_version="synthetic-v1",
        source="UNIVERSITY_OFFICIAL",
        minor_event_conversion_unit=3,
    )

    assert result.score == Decimal("18")
    assert result.trace.equivalent_absence_days == 2
    assert result.trace.minor_event_remainder == 0


def test_attendance_missing_values_are_never_assumed_zero_or_max_score() -> None:
    rows = (_attendance_row("20", 0, None),)
    with pytest.raises(ScoreComponentError):
        convert_attendance(
            attendance=AttendanceInput(None, 0, 0, 0, True),
            table_rows=rows,
            table_code="SYNTHETIC_ATTENDANCE_V1",
            table_version="synthetic-v1",
            source="UNIVERSITY_OFFICIAL",
            minor_event_conversion_unit=3,
        )
    with pytest.raises(ScoreComponentError):
        convert_attendance(
            attendance=AttendanceInput(0, 0, 0, 0, False),
            table_rows=rows,
            table_code="SYNTHETIC_ATTENDANCE_V1",
            table_version="synthetic-v1",
            source="UNIVERSITY_OFFICIAL",
            minor_event_conversion_unit=3,
        )
