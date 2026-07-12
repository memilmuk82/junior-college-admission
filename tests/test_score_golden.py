from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.services.score_calculation import calculate_selected_score
from app.services.score_components import (
    AttendanceInput,
    AttendanceTableRow,
    convert_attendance,
)
from app.services.score_selection import select_terms_and_subjects
from tests.test_score_selection import _definition, _selection, _values


def test_synthetic_grade_weight_and_attendance_golden_trace() -> None:
    definition = replace(
        _definition(),
        value_direction="LOWER_IS_BETTER",
        semester_selection_method="BEST_N",
        semester_selection_scope="PER_GRADE",
        best_semester_count=1,
        weighting_mode="GRADE_ONLY",
        grade_weight_1=Decimal("0.30"),
        grade_weight_2=Decimal("0.30"),
        grade_weight_3=Decimal("0.40"),
        attendance_included=True,
        attendance_table_code="SYNTHETIC_ATTENDANCE_V1",
        attendance_source="UNIVERSITY_OFFICIAL",
        attendance_minor_event_conversion_unit=3,
        maximum_score=Decimal("120"),
    )
    selected = select_terms_and_subjects(_selection(), definition, _values())
    attendance = convert_attendance(
        attendance=AttendanceInput(1, 2, 1, 0, True),
        table_rows=(
            AttendanceTableRow(
                table_code="SYNTHETIC_ATTENDANCE_V1",
                absence_min=0,
                absence_max=1,
                score=Decimal("20"),
                maximum_score=Decimal("20"),
                evidence_document_id="synthetic-guide",
                evidence_page=10,
                evidence_location="합성 출결 표",
                source_status="FINAL_GUIDE",
            ),
            AttendanceTableRow(
                table_code="SYNTHETIC_ATTENDANCE_V1",
                absence_min=2,
                absence_max=None,
                score=Decimal("18"),
                maximum_score=Decimal("20"),
                evidence_document_id="synthetic-guide",
                evidence_page=10,
                evidence_location="합성 출결 표",
                source_status="FINAL_GUIDE",
            ),
        ),
        table_code="SYNTHETIC_ATTENDANCE_V1",
        table_version="synthetic-v1",
        source="UNIVERSITY_OFFICIAL",
        minor_event_conversion_unit=3,
    )

    result = calculate_selected_score(
        selected,
        definition,
        rule_id="synthetic-golden-rule",
        rule_version="synthetic-v1",
        attendance=attendance,
    )

    # 독립 수기식: 1학년 70×0.30 + 2학년 55×0.30 + 3학년 75×0.40 + 출결 18
    assert result.trace.academic_score == Decimal("67.50")
    assert result.pre_round_score == Decimal("85.50")
    assert result.final_score == Decimal("85.50")
    assert result.trace.rule_id == "synthetic-golden-rule"
    assert result.trace.attendance_table_version == "synthetic-v1"
