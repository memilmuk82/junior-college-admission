from __future__ import annotations

import csv
import json
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.services.admission_result_file_imports import (
    AdmissionResultUploadError,
    CatalogMatch,
    parse_admission_result_upload,
)
from scripts.build_phase14_public_admission_seed import _supplemental_index


class SyntheticCatalog:
    def resolve(
        self,
        *,
        institution_name: str,
        campus_name: str | None,
        program_name: str,
        admission_round_name: str,
        admission_track_name: str,
        target_academic_year: int,
    ) -> CatalogMatch | None:
        if institution_name != "합성전문대학" or program_name != "합성학과":
            return None
        return CatalogMatch(
            institution_code="SYNTHETIC-U",
            campus_code="MAIN",
            program_code="SYNTHETIC-P",
            admission_round_code="EARLY-1",
            admission_track_code="GENERAL",
            campus_name=campus_name or "본교",
        )


def _xlsx_bytes() -> bytes:
    workbook = Workbook()
    student = workbook.active
    assert student is not None
    student.title = "성적 입력"
    student.append(["과목", "석차등급"])
    student.append(["개인 성적 원문", 1])
    result = workbook.create_sheet("2027 수시(1차) 결과")
    result.append([])
    result.append(
        [
            "지역",
            "대학명",
            "모집시기",
            "전공명",
            "모집시기별 입학정원",
            "주/야",
            "전형구분1",
            "전형구분2",
            "합격자최저",
            "합격자평균",
        ]
    )
    result.append(
        [
            "서울",
            "합성전문대학",
            "수시1차",
            "합성학과",
            0,
            "주간",
            "특별전형",
            "일반고",
            5.4,
            4.3,
        ]
    )
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def test_xlsx_detects_only_result_sheet_and_preserves_zero() -> None:
    preview = parse_admission_result_upload(
        _xlsx_bytes(),
        filename="public-results.xlsx",
        result_academic_year=2027,
        target_academic_year=2028,
        catalog=SyntheticCatalog(),
    )

    assert preview.result_academic_year == 2027
    assert preview.target_academic_year == 2028
    assert preview.detected_sheets == ("2027 수시(1차) 결과",)
    assert preview.total_row_count == 1
    assert preview.valid_row_count == 1
    assert preview.review_row_count == 0
    row = preview.rows[0]
    assert row.capacity == 0
    assert row.applicant_count is None
    assert str(row.average_score) == "4.3"
    assert str(row.cutoff_score) == "5.4"
    assert row.score_basis == "RANK_GRADE"
    assert row.score_direction == "LOWER_IS_BETTER"
    assert "개인 성적 원문" not in repr(preview)


def test_csv_and_xlsx_create_same_canonical_row() -> None:
    csv_bytes = (
        "지역,대학명,모집시기,전공명,모집시기별 입학정원,주/야,전형구분1,"
        "전형구분2,합격자최저,합격자평균\n"
        "서울,합성전문대학,수시1차,합성학과,0,주간,특별전형,일반고,5.4,4.3\n"
    ).encode()
    csv_preview = parse_admission_result_upload(
        csv_bytes,
        filename="public-results.csv",
        result_academic_year=2027,
        target_academic_year=2028,
        catalog=SyntheticCatalog(),
    )
    xlsx_preview = parse_admission_result_upload(
        _xlsx_bytes(),
        filename="public-results.xlsx",
        result_academic_year=2027,
        target_academic_year=2028,
        catalog=SyntheticCatalog(),
    )

    csv_row = csv_preview.rows[0]
    xlsx_row = xlsx_preview.rows[0]
    comparable_fields = (
        "result_academic_year",
        "target_academic_year",
        "region",
        "institution_code",
        "institution_name",
        "campus_code",
        "program_code",
        "program_name",
        "admission_round_code",
        "admission_round_name",
        "admission_track_code",
        "admission_track_name",
        "capacity",
        "average_score",
        "cutoff_score",
        "score_basis",
        "score_direction",
        "validation_status",
    )
    assert {field: getattr(csv_row, field) for field in comparable_fields} == {
        field: getattr(xlsx_row, field) for field in comparable_fields
    }


def test_unknown_catalog_mapping_stays_in_review() -> None:
    preview = parse_admission_result_upload(
        _xlsx_bytes(),
        filename="public-results.xlsx",
        result_academic_year=2027,
        target_academic_year=2028,
        catalog=None,
    )

    assert preview.valid_row_count == 0
    assert preview.review_row_count == 1
    assert preview.rows[0].validation_status == "REVIEW"
    assert {issue.code for issue in preview.rows[0].issues} == {"CATALOG_MAPPING_REQUIRED"}


def test_csv_formula_injection_is_blocked() -> None:
    csv_bytes = (
        "대학명,모집시기,전공명,전형명,합격자평균\n"
        "=HYPERLINK(https://invalid),수시1차,합성학과,일반고,4.3\n"
    ).encode()
    preview = parse_admission_result_upload(
        csv_bytes,
        filename="public-results.csv",
        result_academic_year=2027,
        target_academic_year=2028,
        catalog=SyntheticCatalog(),
    )

    assert preview.error_row_count == 1
    assert {issue.code for issue in preview.rows[0].issues} == {"FORMULA_NOT_ALLOWED"}


def test_default_target_year_is_result_year_plus_one() -> None:
    preview = parse_admission_result_upload(
        _xlsx_bytes(),
        filename="public-results.xlsx",
        result_academic_year=2027,
        catalog=SyntheticCatalog(),
    )

    assert preview.target_academic_year == 2028


def test_reference_xlsx_has_exact_public_result_counts_without_student_sheet() -> None:
    source_path = Path(
        "tmp/codex-reference/xlsx/OOO_2026 전문대 수시 분석_2027 수도권 전문대 입결_전문대교협.xlsx"
    )
    if not source_path.is_file():
        return
    preview = parse_admission_result_upload(
        source_path.read_bytes(),
        filename=source_path.name,
        result_academic_year=2025,
        target_academic_year=2027,
        catalog=None,
    )

    assert preview.detected_sheets == (
        "2025 수시(1차) 결과",
        "2025 수시(2차) 결과",
    )
    assert preview.total_row_count == 1818 + 1652
    assert preview.review_row_count == 3463
    assert preview.error_row_count == 7
    assert all("성적 입력" not in row.source_reference for row in preview.rows)


def test_public_seed_contains_only_allowlisted_result_columns() -> None:
    seed = Path("data/seed/phase14_public_admission_results_2025.csv").read_text(encoding="utf-8")
    header, *rows = seed.splitlines()

    assert len(rows) == 482
    assert "과목" not in header
    assert "나의 등급" not in header
    assert "합격여부" not in header
    assert "성적 입력" not in seed


def test_xlsx_seed_uses_exact_csv_key_only_for_competition_lineage() -> None:
    supplemental_path = Path("tmp/codex-reference/csv/procollege_all_2026 (1).csv")
    if not supplemental_path.is_file():
        return
    supplemental = _supplemental_index()
    assert len(supplemental) == 484
    with Path("data/seed/phase14_public_admission_results_2025.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        rows = tuple(csv.DictReader(handle))

    assert len(rows) == 482
    assert (
        len(
            {
                (
                    row["대학명"],
                    row["모집시기"],
                    row["전공명"],
                    row["전형구분1"],
                    row["전형구분2"],
                )
                for row in rows
            }
        )
        == 482
    )
    assert all(row["경쟁률"] for row in rows)
    assert all(
        row["source_reference"].startswith(
            "sha256:bde8fe5d513ce2737c08815b0d7e1df366dc8844e6ff7f243eccb63c3bd40606#"
        )
        and "supplemental.competition_rate=sha256:c35d548a" in row["source_reference"]
        for row in rows
    )


def test_all_years_aliases_and_selected_result_year_are_enforced() -> None:
    source = (
        "모집학년도,대학명,모집시기,전공명,전형구분,출신교,입학정원,"
        "경쟁률,평균_학생부,최저_학생부\n"
        "2026,합성전문대학,수시1차,합성학과,특별전형,일반고,20,8.4,5.7,6.3\n"
    ).encode()
    preview = parse_admission_result_upload(
        source,
        filename="all-years.csv",
        result_academic_year=2025,
        target_academic_year=2027,
        catalog=SyntheticCatalog(),
    )

    assert preview.error_row_count == 1
    assert {issue.code for issue in preview.rows[0].issues} == {"RESULT_YEAR_MISMATCH"}
    assert str(preview.rows[0].competition_rate) == "8.4"
    assert str(preview.rows[0].average_score) == "5.7"
    assert str(preview.rows[0].cutoff_score) == "6.3"


def test_versioned_alias_file_accepts_new_header_without_code_change(
    tmp_path: Path,
) -> None:
    default_path = Path("data/seed/phase14_admission_result_column_aliases.json")
    payload = json.loads(default_path.read_text(encoding="utf-8"))
    payload["aliases"]["average_score"].append("학생부 대표값")
    custom_path = tmp_path / "column-aliases.json"
    custom_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    source = (
        "대학명,모집시기,전공명,전형명,학생부 대표값\n합성전문대학,수시1차,합성학과,일반고,4.25\n"
    ).encode()

    preview = parse_admission_result_upload(
        source,
        filename="custom.csv",
        result_academic_year=2027,
        catalog=SyntheticCatalog(),
        column_alias_config_path=custom_path,
    )

    assert preview.valid_row_count == 1
    assert str(preview.rows[0].average_score) == "4.25"


def test_alias_file_rejects_normalized_cross_canonical_collision(tmp_path: Path) -> None:
    default_path = Path("data/seed/phase14_admission_result_column_aliases.json")
    payload = json.loads(default_path.read_text(encoding="utf-8"))
    payload["aliases"]["cutoff_score"].append("평균 학생부")
    custom_path = tmp_path / "conflicting-aliases.json"
    custom_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(AdmissionResultUploadError, match="충돌"):
        parse_admission_result_upload(
            _xlsx_bytes(),
            filename="public-results.xlsx",
            result_academic_year=2027,
            catalog=SyntheticCatalog(),
            column_alias_config_path=custom_path,
        )


def test_admin_column_override_replaces_auto_mapping_and_lists_source_columns() -> None:
    source = (
        "대학명,모집시기,전공명,전형명,합격자평균,관리자선택평균\n"
        "합성전문대학,수시1차,합성학과,일반고,8.8,4.25\n"
    ).encode()

    preview = parse_admission_result_upload(
        source,
        filename="override.csv",
        result_academic_year=2027,
        catalog=SyntheticCatalog(),
        column_overrides={"average_score": "관리자선택평균"},
    )

    assert preview.valid_row_count == 1
    assert str(preview.rows[0].average_score) == "4.25"
    assert dict(preview.column_mapping)["average_score"] == "관리자선택평균"
    assert "합격자평균" in preview.available_source_columns
    assert "관리자선택평균" in preview.available_source_columns


def test_rank_grade_direction_and_range_are_fail_closed() -> None:
    wrong_direction = (
        "대학명,모집시기,전공명,전형명,합격자평균,점수기준,점수방향\n"
        "합성전문대학,수시1차,합성학과,일반고,4.3,RANK_GRADE,HIGHER_IS_BETTER\n"
    ).encode()
    out_of_range = (
        "대학명,모집시기,전공명,전형명,합격자평균,점수기준,점수방향\n"
        "합성전문대학,수시1차,합성학과,일반고,9.1,RANK_GRADE,LOWER_IS_BETTER\n"
    ).encode()

    direction_preview = parse_admission_result_upload(
        wrong_direction,
        filename="results.csv",
        result_academic_year=2027,
        target_academic_year=2028,
        catalog=SyntheticCatalog(),
    )
    range_preview = parse_admission_result_upload(
        out_of_range,
        filename="results.csv",
        result_academic_year=2027,
        target_academic_year=2028,
        catalog=SyntheticCatalog(),
    )

    assert direction_preview.error_row_count == 1
    assert {issue.code for issue in direction_preview.rows[0].issues} == {
        "SCORE_DIRECTION_MISMATCH"
    }
    assert range_preview.error_row_count == 1
    assert {issue.code for issue in range_preview.rows[0].issues} == {"SCORE_OUT_OF_RANGE"}


def test_point_score_stays_in_review_instead_of_grade_comparison() -> None:
    source = (
        "대학명,모집시기,전공명,전형명,합격자평균,점수기준,점수방향\n"
        "합성전문대학,수시1차,합성학과,일반고,800,POINT_SCORE,HIGHER_IS_BETTER\n"
    ).encode()
    preview = parse_admission_result_upload(
        source,
        filename="results.csv",
        result_academic_year=2027,
        target_academic_year=2028,
        catalog=SyntheticCatalog(),
    )

    assert preview.review_row_count == 1
    assert {issue.code for issue in preview.rows[0].issues} == {"SCORE_BASIS_REVIEW_REQUIRED"}
