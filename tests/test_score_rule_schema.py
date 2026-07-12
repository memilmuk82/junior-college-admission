from __future__ import annotations

import csv
from decimal import Decimal
from io import StringIO

from app.services.score_rule_schema import (
    SCORE_RULE_CSV_HEADERS,
    Z_SCORE_TABLE_CSV_HEADERS,
    ManagedScoreRule,
    parse_score_rule_csv,
    parse_z_score_table_csv,
    score_rule_definition_from_payload,
    score_rule_to_payload,
    validate_score_rule_payload,
    write_score_rule_csv,
    write_z_score_table_csv,
)


def _valid_row() -> dict[str, str]:
    row = {header: "" for header in SCORE_RULE_CSV_HEADERS}
    row.update(
        {
            "schema_version": "1",
            "admission_year": "2027",
            "university_code": "SYNTHETIC_U",
            "university_name": "합성 전문대",
            "campus_code": "MAIN",
            "admission_round": "EARLY_1",
            "admission_track_code": "GENERAL",
            "admission_track_name": "합성 일반 전형",
            "rule_version": "synthetic-v1",
            "home_grade_1_included": "TRUE",
            "home_grade_2_included": "TRUE",
            "home_grade_3_semester_1_included": "FALSE",
            "home_grade_3_semester_2_included": "FALSE",
            "vocational_grade_included": "TRUE",
            "vocational_semester_1_included": "TRUE",
            "vocational_semester_2_included": "FALSE",
            "value_direction": "HIGHER_IS_BETTER",
            "semester_selection_method": "BEST_N",
            "semester_selection_scope": "GLOBAL",
            "best_semester_count": "2",
            "subject_selection_method": "BEST_N",
            "best_subject_count": "5",
            "subject_scope": "ALL",
            "credit_weighted": "TRUE",
            "semester_rounding_mode": "ROUND_HALF_UP",
            "semester_rounding_scale": "5",
            "weighting_mode": "GRADE_ONLY",
            "grade_weight_1": "0.30",
            "grade_weight_2": "0.30",
            "grade_weight_3": "0.40",
            "achievement_handling": "EXCLUDE",
            "career_subject_included": "FALSE",
            "z_score_policy": "TABLE_LOOKUP",
            "z_score_source": "UNIVERSITY_OFFICIAL",
            "z_score_table_code": "SYNTHETIC_Z_01",
            "z_score_formula_version": "STANDARD_Z_V1",
            "z_score_rounding_mode": "ROUND_HALF_UP",
            "z_score_rounding_scale": "2",
            "z_score_clip_min": "-3",
            "z_score_clip_max": "3",
            "attendance_included": "FALSE",
            "interview_ratio": "0.20",
            "practical_ratio": "0",
            "rounding_mode": "ROUND_HALF_UP",
            "rounding_stage": "FINAL",
            "rounding_scale": "2",
            "display_scale": "2",
            "score_transform_mode": "IDENTITY",
            "maximum_score": "1000",
            "evidence_document_id": "synthetic-document",
            "evidence_page": "12",
            "evidence_location": "합성 표 1",
            "evidence_level": "UNIVERSITY_OFFICIAL",
            "source_status": "FINAL_GUIDE",
            "change_reason": "합성 규칙 최초 등록",
            "administrator_note": "합성 테스트 전용",
        }
    )
    return row


def _csv_bytes(
    rows: list[dict[str, str]],
    *,
    headers: tuple[str, ...] = SCORE_RULE_CSV_HEADERS,
    bom: bool = False,
) -> bytes:
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    encoding = "utf-8-sig" if bom else "utf-8"
    return output.getvalue().encode(encoding)


def test_utf8_bom_csv_round_trip_uses_same_canonical_rule_schema() -> None:
    parsed = parse_score_rule_csv(_csv_bytes([_valid_row()], bom=True))

    assert parsed.issues == ()
    assert len(parsed.rows) == 1
    direct_payload = score_rule_to_payload(parsed.rows[0])
    validate_score_rule_payload(direct_payload)
    exported = write_score_rule_csv(parsed.rows, include_bom=True)
    reparsed = parse_score_rule_csv(exported)

    assert exported.startswith(b"\xef\xbb\xbf")
    assert reparsed.issues == ()
    assert score_rule_to_payload(reparsed.rows[0]) == direct_payload


def test_canonical_payload_restores_the_same_executable_definition() -> None:
    parsed = parse_score_rule_csv(_csv_bytes([_valid_row()]))
    original = parsed.rows[0].definition

    restored = score_rule_definition_from_payload(score_rule_to_payload(parsed.rows[0]))

    assert restored == original


def test_boolean_codes_are_uppercase_only() -> None:
    row = _valid_row()
    row["credit_weighted"] = "true"

    parsed = parse_score_rule_csv(_csv_bytes([row]))

    assert any(issue.column == "credit_weighted" for issue in parsed.issues)
    assert parsed.rows == ()


def test_blank_and_decimal_zero_remain_distinct() -> None:
    row = _valid_row()
    row["interview_ratio"] = ""
    row["practical_ratio"] = "0"

    parsed = parse_score_rule_csv(_csv_bytes([row]))

    assert parsed.issues == ()
    assert parsed.rows[0].definition.interview_ratio is None
    assert str(parsed.rows[0].definition.practical_ratio) == "0"


def test_minimum_semester_credits_round_trips_as_positive_decimal() -> None:
    row = _valid_row()
    row["minimum_semester_credits"] = "15"

    parsed = parse_score_rule_csv(_csv_bytes([row]))

    assert parsed.issues == ()
    assert parsed.rows[0].definition.minimum_semester_credits == Decimal("15")
    assert parse_score_rule_csv(write_score_rule_csv(parsed.rows)).issues == ()


def test_unknown_header_and_duplicate_business_key_are_explicit() -> None:
    unknown_headers = (*SCORE_RULE_CSV_HEADERS, "formula")
    row = _valid_row()
    row["formula"] = "=1+1"
    unknown = parse_score_rule_csv(_csv_bytes([row], headers=unknown_headers))
    duplicate = parse_score_rule_csv(_csv_bytes([_valid_row(), _valid_row()]))

    assert any(issue.code == "HEADER_MISMATCH" for issue in unknown.issues)
    assert unknown.rows == ()
    assert any(issue.code == "DUPLICATE_KEY" for issue in duplicate.issues)
    assert duplicate.rows == ()


def test_decimal_ratios_validate_range_and_grade_weight_sum() -> None:
    row = _valid_row()
    row["grade_weight_3"] = "0.39"
    row["interview_ratio"] = "1.01"

    parsed = parse_score_rule_csv(_csv_bytes([row]))

    assert {issue.code for issue in parsed.issues} >= {
        "GRADE_WEIGHT_SUM",
        "DECIMAL_RANGE",
    }


def test_semester_weights_round_trip_without_grade_weights() -> None:
    row = _valid_row()
    row["weighting_mode"] = "GLOBAL_SEMESTER"
    for column in ("grade_weight_1", "grade_weight_2", "grade_weight_3"):
        row[column] = ""
    row.update(
        {
            "semester_weight_1_1": "0.10",
            "semester_weight_1_2": "0.10",
            "semester_weight_2_1": "0.20",
            "semester_weight_2_2": "0.30",
            "semester_weight_3_1": "0.30",
            "semester_weight_3_2": "0",
        }
    )

    parsed = parse_score_rule_csv(_csv_bytes([row]))

    assert parsed.issues == ()
    assert parsed.rows[0].definition.semester_weight_3_2 == 0
    assert parse_score_rule_csv(write_score_rule_csv(parsed.rows)).issues == ()


def test_grade_and_semester_weight_modes_cannot_be_mixed() -> None:
    row = _valid_row()
    row["semester_weight_1_1"] = "1"

    parsed = parse_score_rule_csv(_csv_bytes([row]))

    assert any(issue.code == "WEIGHT_MODE_CONFLICT" for issue in parsed.issues)
    assert parsed.rows == ()


def test_hierarchical_grade_and_within_grade_weights_are_valid() -> None:
    row = _valid_row()
    row["weighting_mode"] = "GRADE_WITHIN_SEMESTER"
    row.update(
        {
            "semester_weight_1_1": "0.4",
            "semester_weight_1_2": "0.6",
            "semester_weight_2_1": "0.5",
            "semester_weight_2_2": "0.5",
            "semester_weight_3_1": "1",
            "semester_weight_3_2": "0",
        }
    )

    parsed = parse_score_rule_csv(_csv_bytes([row]))

    assert parsed.issues == ()
    validate_score_rule_payload(score_rule_to_payload(parsed.rows[0]))


def test_limited_linear_score_transform_allows_negative_decimal_multiplier() -> None:
    row = _valid_row()
    row.update(
        {
            "score_transform_mode": "LINEAR",
            "score_base": "950",
            "score_multiplier": "-50",
        }
    )

    parsed = parse_score_rule_csv(_csv_bytes([row]))

    assert parsed.issues == ()
    assert parsed.rows[0].definition.score_multiplier == Decimal("-50")
    assert parse_score_rule_csv(write_score_rule_csv(parsed.rows)).issues == ()


def test_best_selection_requires_positive_count_and_formula_like_text_is_rejected() -> None:
    row = _valid_row()
    row["best_semester_count"] = "0"
    row["administrator_note"] = "=EXECUTABLE_FORMULA"

    parsed = parse_score_rule_csv(_csv_bytes([row]))

    assert {issue.code for issue in parsed.issues} >= {
        "POSITIVE_INTEGER_REQUIRED",
        "FORMULA_LIKE_VALUE",
    }


def test_z_score_source_and_separate_table_code_are_strict() -> None:
    row = _valid_row()
    row["z_score_source"] = "INTERNET_SEARCH"
    row["z_score_table_code"] = ""

    parsed = parse_score_rule_csv(_csv_bytes([row]))

    assert any(issue.column == "z_score_source" for issue in parsed.issues)
    assert any(issue.column == "z_score_table_code" for issue in parsed.issues)


def test_reference_evidence_cannot_claim_university_official_z_source() -> None:
    row = _valid_row()
    row["source_status"] = "VERIFIED_REFERENCE"
    row["evidence_level"] = "VERIFIED_REFERENCE"

    parsed = parse_score_rule_csv(_csv_bytes([row]))

    assert any(issue.code == "OFFICIAL_SOURCE_REQUIRED" for issue in parsed.issues)
    assert parsed.rows == ()


def test_achievement_distribution_and_attendance_tables_are_explicit_rule_links() -> None:
    row = _valid_row()
    row.update(
        {
            "achievement_handling": "DISTRIBUTION",
            "achievement_table_code": "SYNTHETIC_ACHIEVEMENT_V1",
            "achievement_source": "UNIVERSITY_OFFICIAL",
            "achievement_formula_version": "CUMULATIVE_DISTRIBUTION_GRADE_V1",
            "achievement_distribution_scale": "PERCENT",
            "career_subject_included": "TRUE",
            "attendance_included": "TRUE",
            "attendance_table_code": "SYNTHETIC_ATTENDANCE_V1",
            "attendance_source": "UNIVERSITY_OFFICIAL",
            "attendance_minor_event_conversion_unit": "3",
        }
    )

    parsed = parse_score_rule_csv(_csv_bytes([row]))

    assert parsed.issues == ()
    definition = parsed.rows[0].definition
    assert definition.achievement_distribution_scale == "PERCENT"
    assert definition.attendance_minor_event_conversion_unit == 3
    assert parse_score_rule_csv(write_score_rule_csv(parsed.rows)).issues == ()


def test_included_components_cannot_omit_versioned_table_contract() -> None:
    row = _valid_row()
    row["achievement_handling"] = "DISTRIBUTION"
    row["attendance_included"] = "TRUE"

    parsed = parse_score_rule_csv(_csv_bytes([row]))

    assert {issue.code for issue in parsed.issues} >= {
        "ACHIEVEMENT_SETTINGS",
        "ATTENDANCE_SETTINGS",
    }


def test_manual_review_source_allows_incomplete_draft_without_guessing() -> None:
    row = _valid_row()
    row["source_status"] = "MANUAL_REVIEW"
    row["evidence_level"] = "MANUAL_REVIEW"
    row["home_grade_1_included"] = ""
    row["evidence_document_id"] = ""
    row["evidence_page"] = ""
    row["evidence_location"] = ""
    row["z_score_policy"] = "MANUAL_REVIEW"
    row["z_score_source"] = "MANUAL_REVIEW"
    row["z_score_table_code"] = ""

    parsed = parse_score_rule_csv(_csv_bytes([row]))

    assert parsed.issues == ()
    assert parsed.rows[0].definition.home_grade_1_included is None
    assert parsed.rows[0].source_status == "MANUAL_REVIEW"


def _z_csv_bytes(rows: list[dict[str, str]]) -> bytes:
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=Z_SCORE_TABLE_CSV_HEADERS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def test_z_score_tables_use_separate_fixed_csv_without_json_cells() -> None:
    base = {
        "schema_version": "1",
        "table_code": "SYNTHETIC_Z_01",
        "z_min": "1.76",
        "z_min_inclusive": "TRUE",
        "z_max": "",
        "z_max_inclusive": "FALSE",
        "converted_value": "1",
        "evidence_document_id": "synthetic-document",
        "evidence_page": "13",
        "evidence_location": "합성 Z표",
        "source_status": "VERIFIED_REFERENCE",
        "change_reason": "합성 표 등록",
    }
    second = dict(base)
    second.update(
        {
            "z_min": "1.23",
            "z_min_inclusive": "TRUE",
            "z_max": "1.76",
            "z_max_inclusive": "FALSE",
            "converted_value": "2",
        }
    )

    parsed = parse_z_score_table_csv(_z_csv_bytes([base, second]))

    assert parsed.issues == ()
    assert len(parsed.rows) == 2
    assert parsed.rows[0].z_min == Decimal("1.76")
    reparsed = parse_z_score_table_csv(write_z_score_table_csv(parsed.rows))
    assert reparsed.issues == ()
    assert reparsed.rows == parsed.rows


def test_z_score_table_rejects_overlapping_ranges() -> None:
    first = {
        "schema_version": "1",
        "table_code": "SYNTHETIC_Z_01",
        "z_min": "0",
        "z_min_inclusive": "TRUE",
        "z_max": "2",
        "z_max_inclusive": "TRUE",
        "converted_value": "1",
        "evidence_document_id": "synthetic-document",
        "evidence_page": "13",
        "evidence_location": "합성 Z표",
        "source_status": "VERIFIED_REFERENCE",
        "change_reason": "합성 표 등록",
    }
    second = dict(first)
    second.update(
        {
            "z_min": "1",
            "z_max": "3",
            "converted_value": "2",
        }
    )

    parsed = parse_z_score_table_csv(_z_csv_bytes([first, second]))

    assert any(issue.code == "OVERLAPPING_Z_RANGE" for issue in parsed.issues)
    assert parsed.rows == ()


def test_export_accepts_rules_created_by_future_admin_editor() -> None:
    parsed = parse_score_rule_csv(_csv_bytes([_valid_row()]))
    admin_created = ManagedScoreRule(
        identity=parsed.rows[0].identity,
        university_name=parsed.rows[0].university_name,
        admission_track_name=parsed.rows[0].admission_track_name,
        rule_version="admin-v2",
        definition=parsed.rows[0].definition,
        evidence_document_id=parsed.rows[0].evidence_document_id,
        evidence_page=parsed.rows[0].evidence_page,
        evidence_location=parsed.rows[0].evidence_location,
        evidence_level=parsed.rows[0].evidence_level,
        source_status=parsed.rows[0].source_status,
        change_reason="관리자 메뉴 수정",
        administrator_note="동일 canonical schema",
    )

    exported = parse_score_rule_csv(write_score_rule_csv((admin_created,)))

    assert exported.issues == ()
    assert exported.rows[0].rule_version == "admin-v2"


def test_canonical_payload_rejects_extra_formula_field() -> None:
    parsed = parse_score_rule_csv(_csv_bytes([_valid_row()]))
    payload = score_rule_to_payload(parsed.rows[0])
    payload["formula"] = "eval-me"

    try:
        validate_score_rule_payload(payload)
    except ValueError as error:
        assert "canonical" in str(error)
    else:
        raise AssertionError("extra formula field must be rejected")
