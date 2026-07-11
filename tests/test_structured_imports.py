from decimal import Decimal

from app.services.structured_imports import parse_structured_text


def test_csv_normalizes_known_fields_and_preserves_pass_value() -> None:
    source = "\n".join(
        [
            "학년도,학년,학기,교과,과목,이수단위,원점수,평균,표준편차,성취도,수강자수,석차등급",
            "2026,2,1,수학,합성 과목,3,P,,,,,",
        ]
    )

    preview = parse_structured_text(source, source_format="csv")

    assert preview.rows[0].academic_year == 2026
    assert preview.rows[0].credits == Decimal("3")
    assert preview.rows[0].raw_score == "P"
    assert preview.rows[0].course_mean is None
    assert preview.rows[0].rank_grade is None
    assert preview.issues == ()


def test_pasted_table_detects_tabs_and_reports_invalid_number_without_zeroing() -> None:
    source = "학년\t학기\t과목\t원점수\n3\t2\t합성 과목\t확인필요"

    preview = parse_structured_text(source, source_format="pasted_table")

    assert preview.rows[0].raw_score is None
    assert preview.rows[0].subject_name == "합성 과목"
    assert [(issue.code, issue.field, issue.row_number) for issue in preview.issues] == [
        ("INVALID_DECIMAL", "raw_score", 2)
    ]


def test_same_source_produces_same_sha256_without_retaining_unknown_columns() -> None:
    source = "학년,학기,과목,검수제외열\n1,1,합성 과목,저장하지 않음"

    first = parse_structured_text(source, source_format="csv")
    second = parse_structured_text(source, source_format="csv")

    assert first.source_hash == second.source_hash
    assert len(first.source_hash) == 64
    assert not hasattr(first.rows[0], "검수제외열")
    assert first.ignored_headers == ("검수제외열",)


def test_extra_cells_are_not_retained_or_allowed_to_break_preview() -> None:
    source = "학년,학기,과목\n1,1,합성 과목,저장하지 않음"

    preview = parse_structured_text(source, source_format="csv")

    assert len(preview.rows) == 1
    assert preview.rows[0].subject_name == "합성 과목"
