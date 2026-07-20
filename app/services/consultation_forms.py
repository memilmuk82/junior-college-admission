from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.services.consultations import (
    MAX_BATCH_PROGRAMS,
    BatchConsultationRequest,
    ConsultationRequest,
)
from app.services.eligibility import StudentFacts

CONSULTATION_FORM_FIELDS = (
    "student_id",
    "academic_year",
    "program_ids",
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
    request: ConsultationRequest | BatchConsultationRequest | None
    consultation_note: str
    values: dict[str, str]
    errors: tuple[str, ...]
    program_ids: tuple[str, ...] = ()


def parse_consultation_form(form: Mapping[str, str]) -> ConsultationFormResult:
    values = {field: str(form.get(field, "")) for field in CONSULTATION_FORM_FIELDS}
    submitted_program_ids = _multiple_values(form, "program_ids")
    program_ids = tuple(
        dict.fromkeys(value.strip() for value in submitted_program_ids if value.strip())
    )
    errors: list[str] = []
    student_id = values["student_id"].strip()
    track_id = values["admission_track_id"].strip()
    note = values["consultation_note"].strip()
    if not student_id or len(student_id) > 120:
        errors.append("내부 학생 식별자는 1~120자여야 합니다.")
    if any(len(program_id) > 120 for program_id in program_ids):
        errors.append("허용되지 않은 학과 ID가 포함되어 있습니다.")
    if len(program_ids) > MAX_BATCH_PROGRAMS:
        errors.append(f"한 번에 비교할 대학·학과는 최대 {MAX_BATCH_PROGRAMS}개입니다.")
    if not program_ids and not track_id:
        errors.append("희망 대학·학과를 하나 이상 선택해야 합니다.")
    if track_id and len(track_id) > 120:
        errors.append("대상 전형 ID가 유효하지 않습니다.")
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
    academic_year = _optional_nonnegative_int(
        values["academic_year"] or "2027", "모집학년도", errors
    )
    if academic_year is not None and not 2000 <= academic_year <= 2100:
        errors.append("모집학년도는 2000~2100 사이여야 합니다.")
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
    consultation_request: ConsultationRequest | BatchConsultationRequest | None = None
    if not errors and facts is not None:
        if program_ids:
            consultation_request = BatchConsultationRequest(
                student_id=student_id,
                program_ids=program_ids,
                academic_year=academic_year or 2027,
                facts=facts,
                admission_result_year=result_year,
            )
        else:
            consultation_request = ConsultationRequest(
                student_id=student_id,
                admission_track_id=track_id,
                facts=facts,
                admission_result_year=result_year,
            )
    return ConsultationFormResult(consultation_request, note, values, tuple(errors), program_ids)


def _multiple_values(form: Mapping[str, str], field: str) -> tuple[str, ...]:
    getlist = getattr(form, "getlist", None)
    if callable(getlist):
        return tuple(str(value) for value in getlist(field))
    value = form.get(field, "")
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return (str(value),) if value else ()


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
