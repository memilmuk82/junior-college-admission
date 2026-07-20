from __future__ import annotations

from werkzeug.datastructures import MultiDict

from app.services.consultation_forms import parse_consultation_form


def _valid_form() -> dict[str, str]:
    return {
        "student_id": "synthetic-student",
        "admission_track_id": "synthetic-track",
        "home_school_type": "GENERAL",
        "final_school_type": "GENERAL",
        "graduation_status": "EXPECTED",
        "vocational_training_status": "PARTICIPATING",
        "vocational_training_semesters": "1",
        "vocational_training_hours": "",
        "vocational_training_months": "",
        "transferred": "FALSE",
        "ged": "FALSE",
        "admission_result_year": "2026",
        "consultation_note": "합성 상담 메모",
    }


def test_consultation_form_preserves_blank_facts_as_unknown() -> None:
    form = _valid_form()
    form["vocational_training_hours"] = ""
    form["transferred"] = ""

    parsed = parse_consultation_form(form)

    assert parsed.errors == ()
    assert parsed.request is not None
    assert parsed.request.facts.vocational_training_hours is None
    assert parsed.request.facts.transferred is None
    assert parsed.request.admission_result_year == 2026
    assert parsed.consultation_note == "합성 상담 메모"


def test_consultation_form_rejects_invalid_boolean_and_negative_count() -> None:
    form = _valid_form()
    form["ged"] = "0"
    form["vocational_training_hours"] = "-1"

    parsed = parse_consultation_form(form)

    assert parsed.request is None
    assert any("ged" in error for error in parsed.errors)
    assert any("vocational_training_hours" in error for error in parsed.errors)


def test_consultation_form_limits_note_without_persisting_student_identity_fields() -> None:
    form = _valid_form()
    form["consultation_note"] = "가" * 2001

    parsed = parse_consultation_form(form)

    assert parsed.request is None
    assert parsed.errors == ("상담 메모는 2,000자 이하여야 합니다.",)


def test_consultation_form_limits_one_batch_to_five_programs() -> None:
    form = MultiDict(_valid_form())
    form["admission_track_id"] = ""
    for index in range(6):
        form.add("program_ids", f"synthetic-program-{index}")

    parsed = parse_consultation_form(form)

    assert parsed.request is None
    assert parsed.errors == ("한 번에 비교할 대학·학과는 최대 5개입니다.",)
