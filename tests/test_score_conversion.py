from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.score_conversion import ScoreConversionError, convert_z_score
from app.services.score_rule_schema import ZScoreTableRow


def _row(
    grade: str,
    lower: str | None,
    lower_inclusive: bool,
    upper: str | None,
    upper_inclusive: bool,
    *,
    source_status: str = "FINAL_GUIDE",
) -> ZScoreTableRow:
    return ZScoreTableRow(
        table_code="SYNTHETIC_OFFICIAL_Z_V1",
        z_min=None if lower is None else Decimal(lower),
        z_min_inclusive=lower_inclusive,
        z_max=None if upper is None else Decimal(upper),
        z_max_inclusive=upper_inclusive,
        converted_value=Decimal(grade),
        evidence_document_id="synthetic-official-guide",
        evidence_page=10,
        evidence_location="합성 Z점수 표",
        source_status=source_status,
        change_reason="합성 경계 테스트",
    )


def _official_rows() -> tuple[ZScoreTableRow, ...]:
    return (
        _row("1", "1.76", True, None, False),
        _row("2", "1.23", True, "1.76", False),
        _row("3", "0.74", True, "1.23", False),
        _row("4", "0.26", True, "0.74", False),
        _row("5", "-0.26", False, "0.26", False),
        _row("6", "-0.74", False, "-0.26", True),
        _row("7", "-1.23", False, "-0.74", True),
        _row("8", "-1.76", False, "-1.23", True),
        _row("9", None, False, "-1.76", True),
    )


@pytest.mark.parametrize(
    ("z_value", "expected"),
    (("1.76", "1"), ("1.75", "2"), ("-0.25", "5"), ("-0.26", "6"), ("-1.76", "9")),
)
def test_official_boundary_inclusion_is_explicit(z_value: str, expected: str) -> None:
    result = convert_z_score(
        raw_score=Decimal(z_value),
        course_mean=Decimal("0"),
        standard_deviation=Decimal("1"),
        table_rows=_official_rows(),
        table_code="SYNTHETIC_OFFICIAL_Z_V1",
        table_version="synthetic-v1",
        source="UNIVERSITY_OFFICIAL",
        rounding_mode="ROUND_HALF_UP",
        rounding_scale=2,
        clip_min=Decimal("-3"),
        clip_max=Decimal("3"),
    )

    assert result.converted_value == Decimal(expected)
    assert result.trace.official is True
    assert result.trace.table_version == "synthetic-v1"


def test_z_score_missing_or_zero_standard_deviation_is_not_zero_filled() -> None:
    with pytest.raises(ScoreConversionError):
        convert_z_score(
            raw_score=Decimal("80"),
            course_mean=Decimal("70"),
            standard_deviation=Decimal("0"),
            table_rows=_official_rows(),
            table_code="SYNTHETIC_OFFICIAL_Z_V1",
            table_version="synthetic-v1",
            source="UNIVERSITY_OFFICIAL",
            rounding_mode="ROUND_HALF_UP",
            rounding_scale=2,
            clip_min=Decimal("-3"),
            clip_max=Decimal("3"),
        )


def test_reference_table_cannot_be_traced_as_university_official() -> None:
    rows = tuple(
        _row(
            str(row.converted_value),
            None if row.z_min is None else str(row.z_min),
            row.z_min_inclusive,
            None if row.z_max is None else str(row.z_max),
            row.z_max_inclusive,
            source_status="VERIFIED_REFERENCE",
        )
        for row in _official_rows()
    )

    with pytest.raises(ScoreConversionError):
        convert_z_score(
            raw_score=Decimal("1.76"),
            course_mean=Decimal("0"),
            standard_deviation=Decimal("1"),
            table_rows=rows,
            table_code="SYNTHETIC_OFFICIAL_Z_V1",
            table_version="synthetic-reference-v1",
            source="UNIVERSITY_OFFICIAL",
            rounding_mode="ROUND_HALF_UP",
            rounding_scale=2,
            clip_min=None,
            clip_max=None,
        )
