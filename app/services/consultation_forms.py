from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.services.consultations import ConsultationRequest
from app.services.eligibility import StudentFacts

CONSULTATION_FORM_FIELDS = (
    "student_id",
    "admission_track_id",
    "home_school_type",
    "final_school_type",
    "graduation_status",
    "vocational_training_status",
    "vocational_training_semesters",
    "vocational_training_hours",
    "vocational_training_months",
    "transferred",
    "ged",
    "admission_result_year",
    "consultation_note",
)


@dataclass(frozen=True)
class ConsultationFormResult:
    request: ConsultationRequest | None
    consultation_note: str
    values: dict[str, str]
    errors: tuple[str, ...]


def parse_consultation_form(form: Mapping[str, str]) -> ConsultationFormResult:
    values = {field: str(form.get(field, "")) for field in CONSULTATION_FORM_FIELDS}
    errors: list[str] = []
    student_id = values["student_id"].strip()
    track_id = values["admission_track_id"].strip()
    note = values["consultation_note"].strip()
    if not student_id or len(student_id) > 120:
        errors.append("내부 학생 식별자는 1~120자여야 합니다.")
    if not track_id or len(track_id) > 120:
        errors.append("대상 전형을 선택해야 합니다.")
    if len(note) > 2000:
        errors.append("상담 메모는 2,000자 이하여야 합니다.")

    numeric_values: dict[str, int | None] = {}
    for field in (
        "vocational_training_semesters",
        "vocational_training_hours",
        "vocational_training_months",
    ):
        numeric_values[field] = _optional_nonnegative_int(values[field], field, errors)
    result_year = _optional_nonnegative_int(
        values["admission_result_year"], "입시결과 기준연도", errors
    )
    if result_year is not None and result_year < 2000:
        errors.append("입시결과 기준연도는 2000 이상이어야 합니다.")
    boolean_values = {
        field: _optional_boolean(values[field], field, errors) for field in ("transferred", "ged")
    }
    facts: StudentFacts | None = None
    if not errors:
        try:
            facts = StudentFacts(
                home_school_type=values["home_school_type"] or None,
                final_school_type=values["final_school_type"] or None,
                graduation_status=values["graduation_status"] or None,
                vocational_training_status=values["vocational_training_status"] or None,
                vocational_training_semesters=numeric_values["vocational_training_semesters"],
                vocational_training_hours=numeric_values["vocational_training_hours"],
                vocational_training_months=numeric_values["vocational_training_months"],
                transferred=boolean_values["transferred"],
                ged=boolean_values["ged"],
            )
        except ValueError as error:
            errors.append(str(error))
    request: ConsultationRequest | None = None
    if not errors and facts is not None:
        request = ConsultationRequest(
            student_id=student_id,
            admission_track_id=track_id,
            facts=facts,
            admission_result_year=result_year,
        )
    return ConsultationFormResult(request, note, values, tuple(errors))


def _optional_nonnegative_int(value: str, label: str, errors: list[str]) -> int | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = int(normalized)
    except ValueError:
        errors.append(f"{label}은 0 이상의 정수여야 합니다.")
        return None
    if parsed < 0:
        errors.append(f"{label}은 0 이상의 정수여야 합니다.")
        return None
    return parsed


def _optional_boolean(value: str, label: str, errors: list[str]) -> bool | None:
    normalized = value.strip()
    if not normalized:
        return None
    if normalized == "TRUE":
        return True
    if normalized == "FALSE":
        return False
    errors.append(f"{label}은 TRUE 또는 FALSE만 허용합니다.")
    return None


__all__ = [
    "CONSULTATION_FORM_FIELDS",
    "ConsultationFormResult",
    "parse_consultation_form",
]
