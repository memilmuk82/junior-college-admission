from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from werkzeug.datastructures import MultiDict

from app.services.structured_imports import (
    NormalizedCourseRow,
    ScoreValue,
    StructuredImportPreview,
)

EDITABLE_FIELDS = (
    "academic_year",
    "grade",
    "semester",
    "subject_group",
    "subject_name",
    "credits",
    "raw_score",
    "course_mean",
    "standard_deviation",
    "achievement_level",
    "enrollment_count",
    "rank_grade",
    "record_source",
    "is_vocational_training_semester",
)


@dataclass(frozen=True, slots=True)
class ReviewSubmission:
    preview: StructuredImportPreview
    selected_indices: tuple[int, ...]
    values: tuple[dict[str, str], ...]
    field_errors: dict[str, str]
    blocking_errors: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.blocking_errors


def preview_values(preview: StructuredImportPreview) -> tuple[dict[str, str], ...]:
    values: list[dict[str, str]] = []
    for row in preview.rows:
        row_values: dict[str, str] = {}
        for field in EDITABLE_FIELDS:
            value = getattr(row, field)
            if isinstance(value, bool):
                row_values[field] = "TRUE" if value else "FALSE"
            else:
                row_values[field] = "" if value is None else str(value)
        values.append(row_values)
    return tuple(values)


def _integer(value: str, field_key: str, errors: dict[str, str]) -> int | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation:
        errors[field_key] = "정수를 확인하세요."
        return None
    if parsed != parsed.to_integral_value():
        errors[field_key] = "정수를 확인하세요."
        return None
    return int(parsed)


def _decimal(value: str, field_key: str, errors: dict[str, str]) -> Decimal | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        parsed = Decimal(cleaned)
    except InvalidOperation:
        errors[field_key] = "숫자를 확인하세요."
        return None
    if not parsed.is_finite():
        errors[field_key] = "유한한 숫자를 입력하세요."
        return None
    return parsed


def _score(value: str, field_key: str, errors: dict[str, str]) -> ScoreValue:
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned == "P":
        return "P"
    return _decimal(cleaned, field_key, errors)


def _boolean(value: str, field_key: str, errors: dict[str, str]) -> bool | None:
    cleaned = value.strip().upper()
    if not cleaned:
        return None
    if cleaned == "TRUE":
        return True
    if cleaned == "FALSE":
        return False
    errors[field_key] = "예/아니오를 확인하세요."
    return None


def parse_review_submission(
    form: MultiDict[str, str], original: StructuredImportPreview
) -> ReviewSubmission:
    selected_indices: list[int] = []
    blocking_errors: list[str] = []
    for raw_index in form.getlist("confirmed_row_indices"):
        try:
            index = int(raw_index)
        except ValueError:
            blocking_errors.append("선택한 행 정보가 올바르지 않습니다.")
            continue
        if index < 0 or index >= len(original.rows) or index in selected_indices:
            blocking_errors.append("선택한 행 정보가 올바르지 않습니다.")
            continue
        selected_indices.append(index)
    if not selected_indices:
        blocking_errors.append("저장할 행을 선택하세요.")

    field_errors: dict[str, str] = {}
    values: list[dict[str, str]] = []
    rows: list[NormalizedCourseRow] = []
    for index, original_row in enumerate(original.rows):
        row_values = {field: form.get(f"rows-{index}-{field}", "") for field in EDITABLE_FIELDS}
        values.append(row_values)
        row_errors_before = set(field_errors)
        row = NormalizedCourseRow(
            academic_year=_integer(
                row_values["academic_year"],
                f"rows-{index}-academic_year",
                field_errors,
            ),
            grade=_integer(row_values["grade"], f"rows-{index}-grade", field_errors),
            semester=_integer(row_values["semester"], f"rows-{index}-semester", field_errors),
            subject_group=row_values["subject_group"].strip() or None,
            subject_name=row_values["subject_name"].strip() or None,
            credits=_decimal(row_values["credits"], f"rows-{index}-credits", field_errors),
            raw_score=_score(row_values["raw_score"], f"rows-{index}-raw_score", field_errors),
            course_mean=_decimal(
                row_values["course_mean"],
                f"rows-{index}-course_mean",
                field_errors,
            ),
            standard_deviation=_decimal(
                row_values["standard_deviation"],
                f"rows-{index}-standard_deviation",
                field_errors,
            ),
            achievement_level=row_values["achievement_level"].strip() or None,
            enrollment_count=_integer(
                row_values["enrollment_count"],
                f"rows-{index}-enrollment_count",
                field_errors,
            ),
            rank_grade=_decimal(
                row_values["rank_grade"],
                f"rows-{index}-rank_grade",
                field_errors,
            ),
            source_sheet=original_row.source_sheet,
            source_row_number=original_row.source_row_number,
            source_page=original_row.source_page,
            record_source=row_values["record_source"].strip() or None,
            is_vocational_training_semester=_boolean(
                row_values["is_vocational_training_semester"],
                f"rows-{index}-is_vocational_training_semester",
                field_errors,
            ),
        )
        if row.grade is not None and row.grade not in {1, 2, 3}:
            field_errors[f"rows-{index}-grade"] = "학년은 1~3만 입력할 수 있습니다."
        if row.semester is not None and row.semester not in {1, 2}:
            field_errors[f"rows-{index}-semester"] = "학기는 1~2만 입력할 수 있습니다."
        if row.academic_year is not None and not 2000 <= row.academic_year <= 2100:
            field_errors[f"rows-{index}-academic_year"] = "학년도는 2000~2100으로 입력하세요."
        if row.credits is not None and not Decimal("0") < row.credits <= Decimal("999.99"):
            field_errors[f"rows-{index}-credits"] = "이수단위는 0보다 커야 합니다."
        if isinstance(row.raw_score, Decimal) and not Decimal("0") <= row.raw_score <= Decimal(
            "100"
        ):
            field_errors[f"rows-{index}-raw_score"] = "원점수는 0~100으로 입력하세요."
        if row.course_mean is not None and not Decimal("0") <= row.course_mean <= Decimal("100"):
            field_errors[f"rows-{index}-course_mean"] = "과목평균은 0~100으로 입력하세요."
        if row.standard_deviation is not None and row.standard_deviation <= 0:
            field_errors[f"rows-{index}-standard_deviation"] = (
                "표준편차는 0보다 커야 하며 임의 값으로 대체하지 않습니다."
            )
        if row.enrollment_count is not None and not 1 <= row.enrollment_count <= 1_000_000:
            field_errors[f"rows-{index}-enrollment_count"] = "수강자수는 1 이상이어야 합니다."
        if row.rank_grade is not None and not Decimal("1") <= row.rank_grade <= Decimal("9"):
            field_errors[f"rows-{index}-rank_grade"] = "석차등급은 1~9로 입력하세요."
        if index in selected_indices:
            required = {
                "academic_year": row.academic_year,
                "grade": row.grade,
                "semester": row.semester,
                "subject_name": row.subject_name,
            }
            for field, value in required.items():
                field_key = f"rows-{index}-{field}"
                if value is None:
                    field_errors.setdefault(field_key, "필수 값을 입력하세요.")
            new_row_errors = set(field_errors) - row_errors_before
            if new_row_errors:
                blocking_errors.append(f"{index + 1}번 행의 입력값을 확인하세요.")
        rows.append(row)

    preview = StructuredImportPreview(
        source_hash=original.source_hash,
        source_format=original.source_format,
        rows=tuple(rows),
        issues=original.issues,
        ignored_headers=original.ignored_headers,
    )
    return ReviewSubmission(
        preview=preview,
        selected_indices=tuple(selected_indices),
        values=tuple(values),
        field_errors=field_errors,
        blocking_errors=tuple(dict.fromkeys(blocking_errors)),
    )
