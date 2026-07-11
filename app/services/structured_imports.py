from __future__ import annotations

import csv
import hashlib
import io
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

SourceFormat = Literal["csv", "pasted_table"]
ScoreValue = Decimal | Literal["P"] | None

HEADER_ALIASES = {
    "학년도": "academic_year",
    "academic_year": "academic_year",
    "학년": "grade",
    "grade": "grade",
    "학기": "semester",
    "semester": "semester",
    "교과": "subject_group",
    "교과군": "subject_group",
    "subject_group": "subject_group",
    "과목": "subject_name",
    "과목명": "subject_name",
    "subject_name": "subject_name",
    "학점": "credits",
    "이수단위": "credits",
    "credits": "credits",
    "원점수": "raw_score",
    "raw_score": "raw_score",
    "평균": "course_mean",
    "course_mean": "course_mean",
    "표준편차": "standard_deviation",
    "standard_deviation": "standard_deviation",
    "성취도": "achievement_level",
    "achievement_level": "achievement_level",
    "수강자수": "enrollment_count",
    "수강자 수": "enrollment_count",
    "enrollment_count": "enrollment_count",
    "석차등급": "rank_grade",
    "rank_grade": "rank_grade",
}


@dataclass(frozen=True, slots=True)
class NormalizationIssue:
    code: str
    field: str
    row_number: int


@dataclass(frozen=True, slots=True)
class NormalizedCourseRow:
    academic_year: int | None
    grade: int | None
    semester: int | None
    subject_group: str | None
    subject_name: str | None
    credits: Decimal | None
    raw_score: ScoreValue
    course_mean: Decimal | None
    standard_deviation: Decimal | None
    achievement_level: str | None
    enrollment_count: int | None
    rank_grade: Decimal | None


@dataclass(frozen=True, slots=True)
class StructuredImportPreview:
    source_hash: str
    source_format: SourceFormat
    rows: tuple[NormalizedCourseRow, ...]
    issues: tuple[NormalizationIssue, ...]
    ignored_headers: tuple[str, ...]


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_decimal(
    value: str | None,
    *,
    field: str,
    row_number: int,
    issues: list[NormalizationIssue],
) -> Decimal | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation:
        issues.append(NormalizationIssue("INVALID_DECIMAL", field, row_number))
        return None


def _parse_integer(
    value: str | None,
    *,
    field: str,
    row_number: int,
    issues: list[NormalizationIssue],
) -> int | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation:
        issues.append(NormalizationIssue("INVALID_INTEGER", field, row_number))
        return None
    if parsed != parsed.to_integral_value():
        issues.append(NormalizationIssue("INVALID_INTEGER", field, row_number))
        return None
    return int(parsed)


def _delimiter_for(source: str, source_format: SourceFormat) -> str:
    if source_format == "csv":
        return ","
    header = source.splitlines()[0] if source.splitlines() else ""
    if "\t" in header:
        return "\t"
    try:
        return csv.Sniffer().sniff(source, delimiters=",;|").delimiter
    except csv.Error:
        return ","


def _standardized_row(row: Mapping[object, object], header_map: dict[str, str]) -> dict[str, str]:
    standardized: dict[str, str] = {}
    for original_header, value in row.items():
        field = header_map.get(original_header) if isinstance(original_header, str) else None
        if field is not None and isinstance(value, str):
            standardized[field] = value
    return standardized


def parse_structured_text(source: str, *, source_format: SourceFormat) -> StructuredImportPreview:
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    reader = csv.DictReader(io.StringIO(source), delimiter=_delimiter_for(source, source_format))
    raw_headers = tuple(reader.fieldnames or ())
    cleaned_headers = tuple((header or "").removeprefix("\ufeff").strip() for header in raw_headers)
    header_map = {
        raw_header: HEADER_ALIASES[cleaned_header]
        for raw_header, cleaned_header in zip(raw_headers, cleaned_headers, strict=True)
        if cleaned_header in HEADER_ALIASES
    }
    ignored_headers = tuple(
        header for header in cleaned_headers if header and header not in HEADER_ALIASES
    )
    issues: list[NormalizationIssue] = []
    normalized_rows: list[NormalizedCourseRow] = []

    for row_number, raw_row in enumerate(reader, start=2):
        if not any(_clean_text(value) for value in raw_row.values() if isinstance(value, str)):
            continue
        row = _standardized_row(raw_row, header_map)
        subject_name = _clean_text(row.get("subject_name"))
        if subject_name is None:
            issues.append(NormalizationIssue("MISSING_REQUIRED", "subject_name", row_number))

        raw_score_text = _clean_text(row.get("raw_score"))
        if raw_score_text == "P":
            raw_score: ScoreValue = "P"
        else:
            raw_score = _parse_decimal(
                raw_score_text,
                field="raw_score",
                row_number=row_number,
                issues=issues,
            )

        normalized_rows.append(
            NormalizedCourseRow(
                academic_year=_parse_integer(
                    row.get("academic_year"),
                    field="academic_year",
                    row_number=row_number,
                    issues=issues,
                ),
                grade=_parse_integer(
                    row.get("grade"),
                    field="grade",
                    row_number=row_number,
                    issues=issues,
                ),
                semester=_parse_integer(
                    row.get("semester"),
                    field="semester",
                    row_number=row_number,
                    issues=issues,
                ),
                subject_group=_clean_text(row.get("subject_group")),
                subject_name=subject_name,
                credits=_parse_decimal(
                    row.get("credits"),
                    field="credits",
                    row_number=row_number,
                    issues=issues,
                ),
                raw_score=raw_score,
                course_mean=_parse_decimal(
                    row.get("course_mean"),
                    field="course_mean",
                    row_number=row_number,
                    issues=issues,
                ),
                standard_deviation=_parse_decimal(
                    row.get("standard_deviation"),
                    field="standard_deviation",
                    row_number=row_number,
                    issues=issues,
                ),
                achievement_level=_clean_text(row.get("achievement_level")),
                enrollment_count=_parse_integer(
                    row.get("enrollment_count"),
                    field="enrollment_count",
                    row_number=row_number,
                    issues=issues,
                ),
                rank_grade=_parse_decimal(
                    row.get("rank_grade"),
                    field="rank_grade",
                    row_number=row_number,
                    issues=issues,
                ),
            )
        )

    return StructuredImportPreview(
        source_hash=source_hash,
        source_format=source_format,
        rows=tuple(normalized_rows),
        issues=tuple(issues),
        ignored_headers=ignored_headers,
    )
