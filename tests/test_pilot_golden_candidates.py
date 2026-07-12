from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.services.eligibility import (
    EligibilityRule,
    EligibilityStatus,
    StudentFacts,
    evaluate_eligibility_for_verification,
)
from app.services.score_calculation import calculate_selected_score
from app.services.score_components import (
    AttendanceInput,
    AttendanceTableRow,
    convert_attendance,
)
from app.services.score_inputs import (
    AcademicRecordInput,
    CourseRecordInput,
    select_score_inputs_for_verification,
)
from app.services.score_selection import ComparableCourseValue, select_terms_and_subjects
from tests.test_score_selection import _definition


def _course(course_id: str, grade_value: str) -> tuple[CourseRecordInput, ComparableCourseValue]:
    course = CourseRecordInput(
        course_record_id=course_id,
        subject_group="합성 교과",
        subject_name=f"합성 과목 {course_id}",
        credits=Decimal("3"),
        raw_score=None,
        raw_score_label=None,
        course_mean=None,
        standard_deviation=None,
        achievement_level=None,
        enrollment_count=None,
        rank_grade=Decimal(grade_value),
        user_verified=True,
    )
    comparable = ComparableCourseValue(
        course_record_id=course_id,
        normalized_value=Decimal(grade_value),
        value_scale="SYNTHETIC_RANK_GRADE",
        scope_codes=frozenset({"GENERAL_SUBJECTS"}),
    )
    return course, comparable


def test_inha_general_vocational_candidate_golden_from_official_pages_6_and_9() -> None:
    eligibility_rule = EligibilityRule(
        rule_id="inha-2027-general-candidate",
        version="extracted-v1",
        lifecycle_status="EXTRACTED",
        payload={
            "schema_version": 1,
            "cases": [
                {
                    "case_id": "general_vocational_training",
                    "when": {
                        "all": [
                            {"fact": "final_school_type", "op": "eq", "value": "GENERAL"},
                            {
                                "fact": "vocational_training_status",
                                "op": "in",
                                "value": ["PARTICIPATING", "EXPECTED_COMPLETION", "COMPLETED"],
                            },
                        ]
                    },
                    "status": "ELIGIBLE",
                    "reason_code": "OFFICIAL_CANDIDATE_GENERAL_VOCATIONAL_ALLOWED",
                }
            ],
            "default": {
                "status": "NEEDS_REVIEW",
                "reason_code": "OFFICIAL_CANDIDATE_REVIEW_REQUIRED",
            },
        },
        source_citation_id="inha-2027-guide-page-6",
        independent_verified=False,
        golden_test_ref=None,
        human_approved_at=None,
    )
    facts = StudentFacts(
        home_school_type="GENERAL",
        final_school_type="GENERAL",
        graduation_status="EXPECTED",
        vocational_training_status="EXPECTED_COMPLETION",
        vocational_training_semesters=2,
        transferred=False,
        ged=False,
    )
    decision = evaluate_eligibility_for_verification(facts, eligibility_rule)
    assert decision.status is EligibilityStatus.ELIGIBLE

    term_values = {
        (1, 1): "3.00",
        (1, 2): "2.00",
        (2, 1): "1.50",
        (2, 2): "4.00",
        (3, 1): "1.00",
    }
    records: list[AcademicRecordInput] = []
    comparable_values: dict[str, ComparableCourseValue] = {}
    for grade_semester, grade_value in term_values.items():
        grade, semester = grade_semester
        course_id = f"synthetic-{grade}-{semester}"
        course, comparable = _course(course_id, grade_value)
        vocational = (grade, semester) == (3, 1)
        records.append(
            AcademicRecordInput(
                academic_record_id=f"record-{grade}-{semester}",
                academic_year=2024 + grade,
                grade=grade,
                semester=semester,
                record_source=(
                    "VOCATIONAL_TRAINING_RECORD" if vocational else "HOME_SCHOOL_RECORD"
                ),
                is_vocational_training_semester=vocational,
                verification_status="USER_VERIFIED",
                courses=(course,),
            )
        )
        comparable_values[course_id] = comparable

    scoped = select_score_inputs_for_verification(
        records=tuple(records),
        payload={"schema_version": 1, "policy": "EXCLUDE_VOCATIONAL_SEMESTER"},
        eligibility=decision,
        rule_id="inha-2027-grade-scope-candidate",
        rule_version="extracted-v1",
    )
    definition = replace(
        _definition(),
        value_direction="LOWER_IS_BETTER",
        semester_selection_method="BEST_N",
        best_semester_count=1,
        credit_weighted=True,
        semester_rounding_mode="ROUND_HALF_UP",
        semester_rounding_scale=6,
        score_transform_mode="LINEAR",
        score_base=Decimal("225"),
        score_multiplier=Decimal("-25"),
        attendance_included=True,
        attendance_table_code="INHA_2027_ATTENDANCE_CANDIDATE",
        attendance_source="UNIVERSITY_OFFICIAL",
        attendance_minor_event_conversion_unit=3,
        maximum_score=Decimal("220"),
    )
    selected = select_terms_and_subjects(scoped, definition, comparable_values)
    attendance = convert_attendance(
        attendance=AttendanceInput(1, 2, 1, 0, True),
        table_rows=tuple(
            AttendanceTableRow(
                table_code="INHA_2027_ATTENDANCE_CANDIDATE",
                absence_min=days,
                absence_max=None if days == 10 else days,
                score=Decimal(max(0, 20 - days * 2)),
                maximum_score=Decimal("20"),
                evidence_document_id="inha-2027-guide",
                evidence_page=9,
                evidence_location="출결상황에 따른 가산점 표",
                source_status="FINAL_GUIDE",
            )
            for days in range(0, 11)
        ),
        table_code="INHA_2027_ATTENDANCE_CANDIDATE",
        table_version="extracted-v1",
        source="UNIVERSITY_OFFICIAL",
        minor_event_conversion_unit=3,
    )
    result = calculate_selected_score(
        selected,
        definition,
        rule_id="inha-2027-score-candidate",
        rule_version="extracted-v1",
        attendance=attendance,
    )

    assert [(term.grade, term.semester) for term in selected.trace.selected_semesters] == [(2, 1)]
    assert "VOCATIONAL_SEMESTER_EXCLUDED" in scoped.trace.exclusion_reasons
    assert result.trace.academic_score == Decimal("187.500000")
    assert result.trace.attendance_score == Decimal("16")
    assert result.final_score == Decimal("203.50")
