from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.services.eligibility import (
    EligibilityRule,
    EligibilityStatus,
    StudentFacts,
    evaluate_eligibility_for_verification,
)
from app.services.score_calculation import ScoreCalculationResult, calculate_selected_score
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
from app.services.score_selection import (
    ComparableCourseValue,
    ScoreSelectionResult,
    select_terms_and_subjects,
)
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


def test_dongyang_vocational_student_has_track_specific_golden_ranges() -> None:
    facts = StudentFacts(
        home_school_type="GENERAL",
        final_school_type="GENERAL",
        graduation_status="EXPECTED",
        vocational_training_status="EXPECTED_COMPLETION",
        vocational_training_semesters=2,
        transferred=False,
        ged=False,
    )
    base_conditions: list[dict[str, object]] = [
        {"fact": "final_school_type", "op": "eq", "value": "GENERAL"},
        {
            "fact": "vocational_training_status",
            "op": "in",
            "value": ["PARTICIPATING", "EXPECTED_COMPLETION", "COMPLETED"],
        },
    ]

    def eligibility(track: str, *, require_two_semesters: bool) -> EligibilityStatus:
        conditions = list(base_conditions)
        if require_two_semesters:
            conditions.append({"fact": "vocational_training_semesters", "op": "gte", "value": 2})
        rule = EligibilityRule(
            rule_id=f"dongyang-2027-{track}-candidate",
            version="extracted-v1",
            lifecycle_status="EXTRACTED",
            payload={
                "schema_version": 1,
                "cases": [
                    {
                        "case_id": f"{track}_vocational_training",
                        "when": {"all": conditions},
                        "status": "ELIGIBLE",
                        "reason_code": f"OFFICIAL_CANDIDATE_{track.upper()}_ALLOWED",
                    }
                ],
                "default": {
                    "status": "NEEDS_REVIEW",
                    "reason_code": "OFFICIAL_CANDIDATE_REVIEW_REQUIRED",
                },
            },
            source_citation_id=(
                "dongyang-2027-guide-page-9"
                if require_two_semesters
                else "dongyang-2027-guide-page-5"
            ),
            independent_verified=False,
            golden_test_ref=None,
            human_approved_at=None,
        )
        return evaluate_eligibility_for_verification(facts, rule).status

    assert eligibility("general", require_two_semesters=False) is EligibilityStatus.ELIGIBLE
    assert eligibility("vocational", require_two_semesters=True) is EligibilityStatus.ELIGIBLE

    term_values = {
        (1, 1): "3.00",
        (1, 2): "2.00",
        (2, 1): "4.00",
        (2, 2): "5.00",
        (3, 1): "1.00",
    }
    records: list[AcademicRecordInput] = []
    comparable_values: dict[str, ComparableCourseValue] = {}
    for (grade, semester), grade_value in term_values.items():
        course_id = f"dongyang-synthetic-{grade}-{semester}"
        course, comparable = _course(course_id, grade_value)
        vocational = (grade, semester) == (3, 1)
        records.append(
            AcademicRecordInput(
                academic_record_id=f"dongyang-record-{grade}-{semester}",
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

    attendance = convert_attendance(
        attendance=AttendanceInput(1, 2, 0, 0, True),
        table_rows=(
            AttendanceTableRow(
                "DONGYANG_2027_ATTENDANCE_CANDIDATE",
                0,
                0,
                Decimal("100"),
                Decimal("100"),
                "dongyang-2027-guide",
                19,
                "출석 성적 반영방법",
                "FINAL_GUIDE",
            ),
            AttendanceTableRow(
                "DONGYANG_2027_ATTENDANCE_CANDIDATE",
                1,
                2,
                Decimal("90"),
                Decimal("100"),
                "dongyang-2027-guide",
                19,
                "출석 성적 반영방법",
                "FINAL_GUIDE",
            ),
        ),
        table_code="DONGYANG_2027_ATTENDANCE_CANDIDATE",
        table_version="extracted-v1",
        source="UNIVERSITY_OFFICIAL",
        minor_event_conversion_unit=3,
    )

    def calculate(
        track: str, policy: str, include_vocational: bool
    ) -> tuple[ScoreSelectionResult, ScoreCalculationResult]:
        decision_rule = EligibilityRule(
            rule_id=f"dongyang-{track}-eligibility",
            version="extracted-v1",
            lifecycle_status="EXTRACTED",
            payload={
                "schema_version": 1,
                "cases": [
                    {
                        "case_id": "eligible",
                        "when": {"fact": "final_school_type", "op": "eq", "value": "GENERAL"},
                        "status": "ELIGIBLE",
                        "reason_code": "OFFICIAL_CANDIDATE_ALLOWED",
                    }
                ],
                "default": {"status": "NEEDS_REVIEW", "reason_code": "REVIEW_REQUIRED"},
            },
            source_citation_id="dongyang-2027-guide",
            independent_verified=False,
            golden_test_ref=None,
            human_approved_at=None,
        )
        decision = evaluate_eligibility_for_verification(facts, decision_rule)
        scoped = select_score_inputs_for_verification(
            records=tuple(records),
            payload={"schema_version": 1, "policy": policy},
            eligibility=decision,
            rule_id=f"dongyang-{track}-scope",
            rule_version="extracted-v1",
        )
        definition = replace(
            _definition(),
            vocational_grade_included=include_vocational,
            vocational_semester_1_included=include_vocational,
            value_direction="LOWER_IS_BETTER",
            semester_selection_method="BEST_N",
            best_semester_count=2,
            credit_weighted=True,
            semester_rounding_mode="ROUND_HALF_UP",
            semester_rounding_scale=6,
            score_transform_mode="LINEAR",
            score_base=Decimal("950"),
            score_multiplier=Decimal("-50"),
            attendance_included=True,
            attendance_table_code="DONGYANG_2027_ATTENDANCE_CANDIDATE",
            attendance_source="UNIVERSITY_OFFICIAL",
            attendance_minor_event_conversion_unit=3,
            maximum_score=Decimal("1000"),
        )
        selected = select_terms_and_subjects(scoped, definition, comparable_values)
        result = calculate_selected_score(
            selected,
            definition,
            rule_id=f"dongyang-{track}-score",
            rule_version="extracted-v1",
            attendance=attendance,
        )
        return selected, result

    general_selected, general = calculate("general", "EXCLUDE_VOCATIONAL_SEMESTER", False)
    vocational_selected, vocational_result = calculate("vocational", "VOCATIONAL_INCLUDED", True)

    assert [(row.grade, row.semester) for row in general_selected.trace.selected_semesters] == [
        (1, 1),
        (1, 2),
    ]
    assert [(row.grade, row.semester) for row in vocational_selected.trace.selected_semesters] == [
        (1, 2),
        (3, 1),
    ]
    assert general.final_score == Decimal("915.00")
    assert vocational_result.final_score == Decimal("965.00")


def test_yeonsung_special_general_candidate_excludes_vocational_and_low_credit_terms() -> None:
    facts = StudentFacts(
        home_school_type="GENERAL",
        final_school_type="GENERAL",
        graduation_status="EXPECTED",
        vocational_training_status="EXPECTED_COMPLETION",
        vocational_training_semesters=2,
        transferred=False,
        ged=False,
    )
    rule = EligibilityRule(
        rule_id="yeonsung-2027-special-general-candidate",
        version="extracted-v1",
        lifecycle_status="EXTRACTED",
        payload={
            "schema_version": 1,
            "cases": [
                {
                    "case_id": "expected_graduate",
                    "when": {"fact": "graduation_status", "op": "eq", "value": "EXPECTED"},
                    "status": "CONDITIONALLY_ELIGIBLE",
                    "reason_code": "SCHOOL_VIOLENCE_FACT_REQUIRES_CONFIRMATION",
                }
            ],
            "default": {"status": "NEEDS_REVIEW", "reason_code": "REVIEW_REQUIRED"},
        },
        source_citation_id="yeonsung-2027-guide-page-26",
        independent_verified=False,
        golden_test_ref=None,
        human_approved_at=None,
    )
    decision = evaluate_eligibility_for_verification(facts, rule)
    assert decision.status is EligibilityStatus.CONDITIONALLY_ELIGIBLE

    term_settings = {
        (1, 1): ("3.00", 5, False),
        (1, 2): ("2.00", 4, False),
        (2, 1): ("4.00", 5, False),
        (2, 2): ("5.00", 5, False),
        (3, 1): ("1.00", 5, True),
    }
    records: list[AcademicRecordInput] = []
    values: dict[str, ComparableCourseValue] = {}
    for (grade, semester), (grade_value, course_count, vocational) in term_settings.items():
        courses: list[CourseRecordInput] = []
        for index in range(course_count):
            course_id = f"yeonsung-{grade}-{semester}-{index}"
            course, comparable = _course(course_id, grade_value)
            courses.append(course)
            values[course_id] = comparable
        records.append(
            AcademicRecordInput(
                academic_record_id=f"yeonsung-record-{grade}-{semester}",
                academic_year=2024 + grade,
                grade=grade,
                semester=semester,
                record_source=(
                    "VOCATIONAL_TRAINING_RECORD" if vocational else "HOME_SCHOOL_RECORD"
                ),
                is_vocational_training_semester=vocational,
                verification_status="USER_VERIFIED",
                courses=tuple(courses),
            )
        )

    scoped = select_score_inputs_for_verification(
        records=tuple(records),
        payload={"schema_version": 1, "policy": "EXCLUDE_VOCATIONAL_SEMESTER"},
        eligibility=decision,
        rule_id="yeonsung-2027-special-general-scope",
        rule_version="extracted-v1",
    )
    definition = replace(
        _definition(),
        value_direction="LOWER_IS_BETTER",
        semester_selection_method="BEST_N",
        best_semester_count=2,
        credit_weighted=True,
        minimum_semester_credits=Decimal("15"),
        score_transform_mode="LINEAR",
        score_base=Decimal("1050"),
        score_multiplier=Decimal("-50"),
        attendance_included=True,
        attendance_table_code="YEONSUNG_2027_ATTENDANCE_CANDIDATE",
        attendance_source="UNIVERSITY_OFFICIAL",
        attendance_minor_event_conversion_unit=3,
        maximum_score=Decimal("1100"),
    )
    selected = select_terms_and_subjects(scoped, definition, values)
    attendance = convert_attendance(
        attendance=AttendanceInput(1, 2, 0, 0, True),
        table_rows=tuple(
            AttendanceTableRow(
                "YEONSUNG_2027_ATTENDANCE_CANDIDATE",
                days,
                None if days == 10 else days,
                Decimal(max(0, 100 - days * 10)),
                Decimal("100"),
                "yeonsung-2027-guide",
                37,
                "출결가산점 표",
                "FINAL_GUIDE",
            )
            for days in range(11)
        ),
        table_code="YEONSUNG_2027_ATTENDANCE_CANDIDATE",
        table_version="extracted-v1",
        source="UNIVERSITY_OFFICIAL",
        minor_event_conversion_unit=3,
    )
    result = calculate_selected_score(
        selected,
        definition,
        rule_id="yeonsung-2027-special-general-score",
        rule_version="extracted-v1",
        attendance=attendance,
    )

    assert [(row.grade, row.semester) for row in selected.trace.selected_semesters] == [
        (1, 1),
        (2, 1),
    ]
    assert "VOCATIONAL_SEMESTER_EXCLUDED" in scoped.trace.exclusion_reasons
    assert "MINIMUM_SEMESTER_CREDITS_NOT_MET" in selected.trace.exclusion_reasons
    assert result.trace.academic_score == Decimal("875.00")
    assert result.trace.attendance_score == Decimal("90")
    assert result.final_score == Decimal("965.00")


def test_polytech_jungsu_vocational_candidate_uses_grade_rounding_and_30_30_40() -> None:
    facts = StudentFacts(
        home_school_type="GENERAL",
        final_school_type="GENERAL",
        graduation_status="EXPECTED",
        vocational_training_status="EXPECTED_COMPLETION",
        vocational_training_semesters=2,
        transferred=False,
        ged=False,
    )

    def decision_for(track: str) -> EligibilityStatus:
        conditions: list[dict[str, object]] = [
            {"fact": "graduation_status", "op": "eq", "value": "EXPECTED"}
        ]
        if track == "special":
            conditions.append(
                {
                    "fact": "vocational_training_status",
                    "op": "in",
                    "value": ["PARTICIPATING", "EXPECTED_COMPLETION", "COMPLETED"],
                }
            )
        rule = EligibilityRule(
            rule_id=f"polytech-jungsu-2027-{track}-candidate",
            version="extracted-v1",
            lifecycle_status="EXTRACTED",
            payload={
                "schema_version": 1,
                "cases": [
                    {
                        "case_id": f"{track}_vocational_candidate",
                        "when": {"all": conditions},
                        "status": "ELIGIBLE",
                        "reason_code": f"OFFICIAL_CANDIDATE_{track.upper()}_ALLOWED",
                    }
                ],
                "default": {"status": "NEEDS_REVIEW", "reason_code": "REVIEW_REQUIRED"},
            },
            source_citation_id="polytech-jungsu-2027-guide-page-7",
            independent_verified=False,
            golden_test_ref=None,
            human_approved_at=None,
        )
        return evaluate_eligibility_for_verification(facts, rule).status

    assert decision_for("general") is EligibilityStatus.ELIGIBLE
    assert decision_for("special") is EligibilityStatus.ELIGIBLE

    term_values = {
        (1, 1): ("2.11115", False),
        (1, 2): ("3.22225", False),
        (2, 1): ("4.11114", False),
        (2, 2): ("5.22224", False),
        (3, 1): ("1.55555", True),
    }
    records: list[AcademicRecordInput] = []
    values: dict[str, ComparableCourseValue] = {}
    for (grade, semester), (grade_value, vocational) in term_values.items():
        course_id = f"polytech-jungsu-{grade}-{semester}"
        course, comparable = _course(course_id, grade_value)
        records.append(
            AcademicRecordInput(
                academic_record_id=f"polytech-jungsu-record-{grade}-{semester}",
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
        values[course_id] = comparable

    eligibility_rule = EligibilityRule(
        rule_id="polytech-jungsu-2027-special-execution-candidate",
        version="extracted-v1",
        lifecycle_status="EXTRACTED",
        payload={
            "schema_version": 1,
            "cases": [
                {
                    "case_id": "vocational_candidate",
                    "when": {
                        "fact": "vocational_training_status",
                        "op": "eq",
                        "value": "EXPECTED_COMPLETION",
                    },
                    "status": "ELIGIBLE",
                    "reason_code": "OFFICIAL_CANDIDATE_SPECIAL_ALLOWED",
                }
            ],
            "default": {"status": "NEEDS_REVIEW", "reason_code": "REVIEW_REQUIRED"},
        },
        source_citation_id="polytech-jungsu-2027-guide-page-7",
        independent_verified=False,
        golden_test_ref=None,
        human_approved_at=None,
    )
    eligibility = evaluate_eligibility_for_verification(facts, eligibility_rule)
    scoped = select_score_inputs_for_verification(
        records=tuple(records),
        payload={"schema_version": 1, "policy": "VOCATIONAL_INCLUDED"},
        eligibility=eligibility,
        rule_id="polytech-jungsu-2027-grade-scope-candidate",
        rule_version="extracted-v1",
    )
    definition = replace(
        _definition(),
        vocational_grade_included=True,
        vocational_semester_1_included=True,
        value_direction="LOWER_IS_BETTER",
        credit_weighted=True,
        semester_rounding_mode="ROUND_HALF_UP",
        semester_rounding_scale=4,
        grade_rounding_mode="ROUND_HALF_UP",
        grade_rounding_scale=2,
        weighting_mode="GRADE_ONLY",
        grade_weight_1=Decimal("0.30"),
        grade_weight_2=Decimal("0.30"),
        grade_weight_3=Decimal("0.40"),
        score_transform_mode="LINEAR",
        score_base=Decimal("334"),
        score_multiplier=Decimal("-14"),
        attendance_included=True,
        attendance_table_code="POLYTECH_JUNGSU_2027_ATTENDANCE_CANDIDATE",
        attendance_source="UNIVERSITY_OFFICIAL",
        attendance_minor_event_conversion_unit=3,
        maximum_score=Decimal("400"),
    )
    selected = select_terms_and_subjects(scoped, definition, values)
    attendance_rows = (
        (0, 0, "80"),
        (1, 2, "71.25"),
        (3, 5, "62.5"),
        (6, 9, "53.75"),
        (10, 15, "45"),
        (16, 20, "36.25"),
        (21, 25, "27.5"),
        (26, 30, "18.75"),
        (31, None, "10"),
    )
    attendance = convert_attendance(
        attendance=AttendanceInput(0, 0, 0, 0, True),
        table_rows=tuple(
            AttendanceTableRow(
                "POLYTECH_JUNGSU_2027_ATTENDANCE_CANDIDATE",
                minimum,
                maximum,
                Decimal(score),
                Decimal("80"),
                "polytech-jungsu-2027-guide",
                9,
                "학교생활기록부 교과성적 및 출석성적 등급표",
                "FINAL_GUIDE",
            )
            for minimum, maximum, score in attendance_rows
        ),
        table_code="POLYTECH_JUNGSU_2027_ATTENDANCE_CANDIDATE",
        table_version="extracted-v1",
        source="UNIVERSITY_OFFICIAL",
        minor_event_conversion_unit=3,
    )
    result = calculate_selected_score(
        selected,
        definition,
        rule_id="polytech-jungsu-2027-score-candidate",
        rule_version="extracted-v1",
        attendance=attendance,
    )

    assert [component.value for component in result.trace.components] == [
        Decimal("2.67"),
        Decimal("4.67"),
        Decimal("1.56"),
    ]
    assert result.trace.aggregate_value == Decimal("2.8260")
    assert result.trace.academic_score == Decimal("294.4360")
    assert result.trace.attendance_score == Decimal("80")
    assert result.final_score == Decimal("374.44")

    xlsx_reference_aggregate = (
        ((Decimal("2.11115") + Decimal("3.22225")) / Decimal(2)) * Decimal("0.30")
        + ((Decimal("4.11114") + Decimal("5.22224")) / Decimal(2)) * Decimal("0.30")
        + Decimal("1.55555") * Decimal("0.40")
    )
    xlsx_reference_score = (
        Decimal("334") - Decimal("14") * xlsx_reference_aggregate + Decimal("80")
    ).quantize(Decimal("0.01"))
    assert xlsx_reference_score == Decimal("374.49")
    assert xlsx_reference_score != result.final_score
