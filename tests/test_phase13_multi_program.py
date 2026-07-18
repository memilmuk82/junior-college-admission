from __future__ import annotations

from pathlib import Path

from werkzeug.datastructures import MultiDict

from app.services.ai_payloads import build_anonymous_consultation_payload, validated_payload_copy
from app.services.consultation_forms import parse_consultation_form
from app.services.consultations import BatchConsultationRequest, ConsultationItemStatus
from app.services.demo_consultations import (
    DEMO_CONSULTATION_DEFAULTS,
    DEMO_DEFAULT_PROGRAM_IDS,
    run_demo_batch_consultation,
)


def _multi_form(*program_ids: str) -> MultiDict[str, str]:
    form = MultiDict((key, str(value)) for key, value in DEMO_CONSULTATION_DEFAULTS.items())
    for program_id in program_ids:
        form.add("program_ids", program_id)
    return form


def test_program_ids_use_getlist_preserve_first_order_and_remove_duplicates() -> None:
    parsed = parse_consultation_form(
        _multi_form("demo-program-care", "demo-program-ai", "demo-program-care")
    )

    assert parsed.errors == ()
    assert isinstance(parsed.request, BatchConsultationRequest)
    assert parsed.request.program_ids == ("demo-program-care", "demo-program-ai")
    assert parsed.request.academic_year == 2027


def test_empty_program_selection_is_rejected_before_evaluation() -> None:
    values = dict(DEMO_CONSULTATION_DEFAULTS)
    values["admission_track_id"] = ""

    parsed = parse_consultation_form(values)

    assert parsed.request is None
    assert "희망 대학·학과를 하나 이상 선택해야 합니다." in parsed.errors


def test_demo_expands_programs_to_independent_tracks_and_isolates_states() -> None:
    parsed = parse_consultation_form(_multi_form(*DEMO_DEFAULT_PROGRAM_IDS))
    assert isinstance(parsed.request, BatchConsultationRequest)

    result = run_demo_batch_consultation(parsed.request)

    assert len(result.selected_programs) == 3
    assert len(result.items) == 5
    same_program = [item for item in result.items if item.program.program_id == "demo-program-ai"]
    assert len(same_program) == 2
    assert all(item.result is not None for item in same_program)
    assert {
        item.result.eligibility.status.value for item in same_program if item.result is not None
    } == {"ELIGIBLE"}
    assert {
        str(item.result.reflected_grade.display_average_grade)
        for item in same_program
        if item.result is not None and item.result.reflected_grade is not None
    } == {"1.75", "2.17"}

    ineligible = next(
        item
        for item in result.items
        if item.result is not None and item.result.eligibility.status.value == "INELIGIBLE"
    )
    assert ineligible.result is not None
    assert ineligible.result.score_input is None
    assert ineligible.result.score_selection is None
    assert ineligible.result.reflected_grade is None
    assert any(item.status is ConsultationItemStatus.PREPARING for item in result.items)
    assert any("복수지원 가능 여부" in warning for warning in result.warnings)


def test_reflected_grade_trace_preserves_courses_credits_weights_and_rounding() -> None:
    parsed = parse_consultation_form(_multi_form("demo-program-ai", "demo-program-care"))
    assert isinstance(parsed.request, BatchConsultationRequest)
    result = run_demo_batch_consultation(parsed.request)
    reflected = [
        item.result.reflected_grade
        for item in result.items
        if item.result is not None and item.result.reflected_grade is not None
    ]

    assert reflected
    assert all(grade.grade_scale.endswith("RANK_GRADE") for grade in reflected)
    assert all(grade.trace.selected_courses for grade in reflected)
    assert all(
        course.credits is not None and course.rank_grade is not None
        for grade in reflected
        for course in grade.trace.selected_courses
    )
    assert all(
        sum(component.weight for component in grade.trace.components) == 1 for grade in reflected
    )
    assert all(grade.trace.rounding_stage == "DISPLAY_ONLY" for grade in reflected)


def test_ai_schema_v2_contains_multiple_average_grades_without_student_identifier() -> None:
    parsed = parse_consultation_form(_multi_form(*DEMO_DEFAULT_PROGRAM_IDS))
    assert isinstance(parsed.request, BatchConsultationRequest)
    result = run_demo_batch_consultation(parsed.request)

    payload = build_anonymous_consultation_payload(result)
    copied = validated_payload_copy(payload)

    assert payload.schema_version == 2
    assert len(copied["results"]) == 5
    assert "student_id" not in payload.canonical_json
    assert "demo-student" not in payload.canonical_json
    assert "maximum_score" not in payload.canonical_json
    assert any(row["average_grade"] is not None for row in copied["results"])


def test_result_and_print_templates_do_not_expose_point_conversion_as_core_result() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "app/templates/admin_consultation_result.html",
        "app/templates/consultation_print.html",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert "환산점수" not in source
        assert "maximum_score" not in source
        assert "대학별 반영 평균등급" in source or "학생 반영 평균등급" in source
