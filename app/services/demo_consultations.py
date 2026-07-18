from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.services.admission_result_analysis import AdmissionResultAnalysisInput
from app.services.admission_results import AdmissionResultKey, HistoricalRuleReference
from app.services.consultations import (
    AdmissionResultComparison,
    AdmissionResultComparisonStatus,
    BatchConsultationItem,
    BatchConsultationRequest,
    BatchConsultationResult,
    ConsultationError,
    ConsultationEvidence,
    ConsultationItemStatus,
    ConsultationProgram,
    ConsultationRequest,
    ConsultationResult,
    ConsultationStatus,
    ConsultationTarget,
)
from app.services.eligibility import (
    EligibilityRule,
    evaluate_synthetic_demo_eligibility,
)
from app.services.score_calculation import calculate_reflected_grade
from app.services.score_inputs import (
    AcademicRecordInput,
    CourseRecordInput,
    ScoreInputStatus,
    select_score_inputs_for_verification,
)
from app.services.score_rule_schema import ScoreRuleDefinition
from app.services.score_selection import ComparableCourseValue, select_terms_and_subjects

DEMO_TRACK_ID = "demo-synthetic-track"
DEMO_STUDENT_ID = "demo-student"
DEMO_RULE_VERSION = "demo-synthetic-v1"

DEMO_TARGET = ConsultationTarget(
    admission_track_id=DEMO_TRACK_ID,
    academic_year=2027,
    institution_name="가상 미래전문대",
    campus_name="가상 본교",
    program_name="AI융합과(합성)",
    program_code="DEMO_AI",
    admission_round_name="수시 1차(합성)",
    admission_round_code="DEMO_EARLY_1",
    admission_track_name="일반고 전형(합성)",
    admission_track_code="DEMO_GENERAL",
)

DEMO_SPECIAL_TRACK_ID = "demo-synthetic-special-track"
DEMO_PROGRAMS = (
    ConsultationProgram(
        "demo-program-ai",
        2027,
        "가상 미래전문대",
        "가상 본교",
        "AI융합과(합성)",
        "DEMO_AI",
    ),
    ConsultationProgram(
        "demo-program-care",
        2027,
        "가상 새봄전문대",
        "가상 도심캠퍼스",
        "돌봄서비스과(합성)",
        "DEMO_CARE",
    ),
    ConsultationProgram(
        "demo-program-design",
        2027,
        "가상 한빛전문대",
        "가상 창작캠퍼스",
        "콘텐츠디자인과(합성)",
        "DEMO_DESIGN",
    ),
)
DEMO_DEFAULT_PROGRAM_IDS = tuple(program.program_id for program in DEMO_PROGRAMS)

DEMO_CONSULTATION_DEFAULTS = {
    "student_id": DEMO_STUDENT_ID,
    "academic_year": "2027",
    "admission_track_id": DEMO_TRACK_ID,
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
    "consultation_note": "가상 학생의 포트폴리오 체험용 상담입니다.",
}

DEMO_WARNING = (
    "이 결과의 학생·대학·전형·성적·입시결과는 모두 포트폴리오 체험용 합성 예시이며 "
    "실제 지원 판단에 사용할 수 없습니다."
)


def demo_consultation_targets() -> tuple[ConsultationTarget, ...]:
    return (DEMO_TARGET,)


def demo_consultation_programs() -> tuple[ConsultationProgram, ...]:
    return DEMO_PROGRAMS


def run_demo_consultation(request: ConsultationRequest) -> ConsultationResult:
    if request.admission_track_id != DEMO_TRACK_ID or request.student_id != DEMO_STUDENT_ID:
        raise ConsultationError("공개 데모에서는 준비된 합성 학생과 전형만 사용할 수 있습니다.")

    eligibility = evaluate_synthetic_demo_eligibility(
        request.facts,
        EligibilityRule(
            rule_id="demo-synthetic-eligibility",
            version=DEMO_RULE_VERSION,
            lifecycle_status="DEMO_SYNTHETIC",
            payload={
                "schema_version": 1,
                "cases": [
                    {
                        "case_id": "demo_general_student",
                        "when": {"fact": "final_school_type", "op": "eq", "value": "GENERAL"},
                        "status": "ELIGIBLE",
                        "reason_code": "DEMO_GENERAL_ALLOWED",
                    }
                ],
                "default": {
                    "status": "INELIGIBLE",
                    "reason_code": "DEMO_TRACK_NOT_ALLOWED",
                },
            },
            source_citation_id=None,
            independent_verified=False,
            golden_test_ref=None,
            human_approved_at=None,
        ),
    )
    evidence = (
        _evidence("ELIGIBILITY", "demo-synthetic-eligibility"),
        _evidence("GRADE_SOURCE_SCOPE", "demo-synthetic-scope"),
        _evidence("SCORE", "demo-synthetic-score"),
    )
    no_result = AdmissionResultComparison(
        AdmissionResultComparisonStatus.NOT_AVAILABLE,
        None,
        "합성 비교 연도를 선택하지 않았습니다.",
    )
    if not eligibility.allows_score_calculation:
        return ConsultationResult(
            status=ConsultationStatus.ELIGIBILITY_BLOCKED,
            target=DEMO_TARGET,
            eligibility=eligibility,
            score_input=None,
            score_selection=None,
            score=None,
            evidence=(evidence[0],),
            admission_result=no_result,
            warnings=(
                DEMO_WARNING,
                "지원자격이 허용되지 않아 합성 성적 계산을 시작하지 않았습니다.",
            ),
        )

    records = _academic_records()
    score_input = select_score_inputs_for_verification(
        records=records,
        payload={"schema_version": 1, "policy": "HOME_ONLY"},
        eligibility=eligibility,
        rule_id="demo-synthetic-scope",
        rule_version=DEMO_RULE_VERSION,
    )
    definition = _score_definition()
    course_values = {
        course.course_record_id: ComparableCourseValue(
            course_record_id=course.course_record_id,
            normalized_value=course.rank_grade,
            value_scale="DEMO_SYNTHETIC_RANK_GRADE",
            scope_codes=frozenset({"ALL", "GENERAL_SUBJECTS"}),
        )
        for record in records
        for course in record.courses
        if course.rank_grade is not None
    }
    selection = select_terms_and_subjects(score_input, definition, course_values)
    if (
        score_input.status is not ScoreInputStatus.READY
        or selection.status is not ScoreInputStatus.READY
    ):
        return ConsultationResult(
            status=ConsultationStatus.INSUFFICIENT_DATA,
            target=DEMO_TARGET,
            eligibility=eligibility,
            score_input=score_input,
            score_selection=selection,
            score=None,
            evidence=evidence,
            admission_result=no_result,
            warnings=(DEMO_WARNING, "합성 성적 선택 결과를 확인해야 합니다."),
        )
    reflected_grade = calculate_reflected_grade(
        selection,
        definition,
        rule_id="demo-synthetic-score",
        rule_version=DEMO_RULE_VERSION,
    )
    comparison = (
        _demo_admission_result()
        if request.admission_result_year == 2026
        else AdmissionResultComparison(
            AdmissionResultComparisonStatus.NOT_AVAILABLE,
            None,
            "2026 합성 입시결과를 선택한 경우에만 비교 예시를 표시합니다.",
        )
    )
    return ConsultationResult(
        status=ConsultationStatus.READY,
        target=DEMO_TARGET,
        eligibility=eligibility,
        score_input=score_input,
        score_selection=selection,
        score=None,
        evidence=evidence,
        admission_result=comparison,
        warnings=(DEMO_WARNING,),
        reflected_grade=reflected_grade,
    )


def run_demo_batch_consultation(request: BatchConsultationRequest) -> BatchConsultationResult:
    if request.student_id != DEMO_STUDENT_ID or request.academic_year != 2027:
        raise ConsultationError("공개 데모에서는 준비된 합성 학생과 2027학년도만 사용합니다.")
    available = {program.program_id: program for program in DEMO_PROGRAMS}
    if any(program_id not in available for program_id in request.program_ids):
        raise ConsultationError("공개 데모에 허용되지 않은 학과 ID가 포함되어 있습니다.")
    selected = tuple(available[program_id] for program_id in request.program_ids)
    items: list[BatchConsultationItem] = []
    for program in selected:
        if program.program_id == "demo-program-ai":
            legacy = run_demo_consultation(
                ConsultationRequest(
                    request.student_id,
                    DEMO_TRACK_ID,
                    request.facts,
                    request.admission_result_year,
                )
            )
            items.append(
                BatchConsultationItem(
                    program, legacy.target, ConsultationItemStatus.EVALUATED, legacy
                )
            )
            special_target = ConsultationTarget(
                DEMO_SPECIAL_TRACK_ID,
                2027,
                program.institution_name,
                program.campus_name,
                program.program_name,
                program.program_code,
                "수시 1차(합성)",
                "DEMO_EARLY_1",
                "특성화고 전형(합성)",
                "DEMO_VOCATIONAL",
            )
            items.append(
                BatchConsultationItem(
                    program,
                    special_target,
                    ConsultationItemStatus.EVALUATED,
                    _run_demo_variant(
                        request,
                        special_target,
                        scope_policy="VOCATIONAL_INCLUDED",
                        definition=_all_semester_definition(),
                        reason_code="DEMO_VOCATIONAL_CURRICULUM_ALLOWED",
                    ),
                )
            )
        elif program.program_id == "demo-program-care":
            target = _program_target(program, "일반고 전형(합성)", "DEMO_CARE_GENERAL")
            items.append(
                BatchConsultationItem(
                    program,
                    target,
                    ConsultationItemStatus.EVALUATED,
                    _run_demo_variant(
                        request,
                        target,
                        scope_policy="HOME_ONLY",
                        definition=_grade_weighted_definition(),
                        reason_code="DEMO_CARE_GENERAL_ALLOWED",
                    ),
                )
            )
            vocational_target = _program_target(
                program, "특성화고 전형(합성)", "DEMO_CARE_VOCATIONAL"
            )
            items.append(
                BatchConsultationItem(
                    program,
                    vocational_target,
                    ConsultationItemStatus.EVALUATED,
                    _run_demo_variant(
                        request,
                        vocational_target,
                        scope_policy="VOCATIONAL_ONLY",
                        definition=_all_semester_definition(),
                        reason_code="DEMO_CARE_VOCATIONAL_ALLOWED",
                        allowed_school_type="VOCATIONAL",
                    ),
                )
            )
        else:
            items.append(
                BatchConsultationItem(
                    program,
                    _program_target(program, "전형 준비 중(합성)", "DEMO_PREPARING"),
                    ConsultationItemStatus.PREPARING,
                    None,
                    "계산 기준 준비 중: 합성 규칙 검수 상태를 보여주는 예시입니다.",
                )
            )
    return BatchConsultationResult(
        2027,
        selected,
        tuple(items),
        (
            DEMO_WARNING,
            "복수지원 가능 여부는 전형별 지원자격과 별도이며 합성 데모에서는 판정하지 않습니다.",
        ),
    )


def _program_target(
    program: ConsultationProgram, track_name: str, track_code: str
) -> ConsultationTarget:
    return ConsultationTarget(
        f"{program.program_id}-{track_code.lower()}",
        2027,
        program.institution_name,
        program.campus_name,
        program.program_name,
        program.program_code,
        "수시 1차(합성)",
        "DEMO_EARLY_1",
        track_name,
        track_code,
    )


def _run_demo_variant(
    request: BatchConsultationRequest,
    target: ConsultationTarget,
    *,
    scope_policy: str,
    definition: ScoreRuleDefinition,
    reason_code: str,
    allowed_school_type: str = "GENERAL",
) -> ConsultationResult:
    eligibility_rule_id = f"demo-synthetic-{target.admission_track_id}-eligibility"
    eligibility = evaluate_synthetic_demo_eligibility(
        request.facts,
        EligibilityRule(
            rule_id=eligibility_rule_id,
            version=DEMO_RULE_VERSION,
            lifecycle_status="DEMO_SYNTHETIC",
            payload={
                "schema_version": 1,
                "cases": [
                    {
                        "case_id": "demo_general_vocational_student",
                        "when": {
                            "fact": "final_school_type",
                            "op": "eq",
                            "value": allowed_school_type,
                        },
                        "status": "ELIGIBLE",
                        "reason_code": reason_code,
                    }
                ],
                "default": {"status": "INELIGIBLE", "reason_code": "DEMO_TRACK_NOT_ALLOWED"},
            },
            source_citation_id=None,
            independent_verified=False,
            golden_test_ref=None,
            human_approved_at=None,
        ),
    )
    evidence = (
        _evidence("ELIGIBILITY", eligibility_rule_id),
        _evidence("GRADE_SOURCE_SCOPE", f"{target.admission_track_id}-scope"),
        _evidence("SCORE", f"{target.admission_track_id}-score"),
    )
    unavailable = AdmissionResultComparison(
        AdmissionResultComparisonStatus.NOT_AVAILABLE,
        None,
        "합성 공개 평균등급 자료가 없습니다.",
    )
    if not eligibility.allows_score_calculation:
        return ConsultationResult(
            ConsultationStatus.ELIGIBILITY_BLOCKED,
            target,
            eligibility,
            None,
            None,
            None,
            (evidence[0],),
            unavailable,
            (DEMO_WARNING, "지원자격 판정 뒤 합성 성적 조회·계산을 차단했습니다."),
        )
    records = _academic_records()
    score_input = select_score_inputs_for_verification(
        records=records,
        payload={"schema_version": 1, "policy": scope_policy},
        eligibility=eligibility,
        rule_id=f"{target.admission_track_id}-scope",
        rule_version=DEMO_RULE_VERSION,
    )
    course_values = {
        course.course_record_id: ComparableCourseValue(
            course.course_record_id,
            course.rank_grade,
            "DEMO_SYNTHETIC_RANK_GRADE",
            frozenset({"ALL", "GENERAL_SUBJECTS"}),
        )
        for record in records
        for course in record.courses
        if course.rank_grade is not None
    }
    selection = select_terms_and_subjects(score_input, definition, course_values)
    reflected = calculate_reflected_grade(
        selection,
        definition,
        rule_id=f"{target.admission_track_id}-score",
        rule_version=DEMO_RULE_VERSION,
    )
    return ConsultationResult(
        ConsultationStatus.READY,
        target,
        eligibility,
        score_input,
        selection,
        None,
        evidence,
        _variant_admission_result(target, request.admission_result_year),
        (DEMO_WARNING,),
        reflected,
    )


def _variant_admission_result(
    target: ConsultationTarget, result_year: int | None
) -> AdmissionResultComparison:
    if result_year != 2026 or target.program_code is None:
        return AdmissionResultComparison(
            AdmissionResultComparisonStatus.NOT_AVAILABLE,
            None,
            "2026 합성 입시결과를 선택한 경우에만 비교 예시를 표시합니다.",
        )
    result = AdmissionResultAnalysisInput(
        key=AdmissionResultKey(
            2026,
            f"{target.program_code}_U",
            "DEMO_MAIN",
            target.admission_round_code,
            target.admission_track_code,
            target.program_code,
        ),
        publication_version="demo-synthetic-result-v1",
        applicant_count=90,
        admitted_count=30,
        competition_rate=Decimal("3.00"),
        highest_score=Decimal("1.40"),
        average_score=Decimal("2.80"),
        lowest_score=Decimal("4.20"),
        score_basis="DEMO_SYNTHETIC_RANK_GRADE",
        historical_rule=HistoricalRuleReference(
            f"{target.admission_track_id}-score-2026", "demo-synthetic-2026-v1", 2026
        ),
    )
    return AdmissionResultComparison(
        AdmissionResultComparisonStatus.REFERENCE_ONLY,
        result,
        "합성 예시이며 현재 규칙 연도와 달라 참고용으로만 표시합니다.",
    )


def _all_semester_definition() -> ScoreRuleDefinition:
    return replace(
        _score_definition(),
        home_grade_3_semester_1_included=True,
        vocational_grade_included=True,
        vocational_semester_1_included=True,
        semester_selection_method="ALL",
        best_semester_count=None,
    )


def _grade_weighted_definition() -> ScoreRuleDefinition:
    return replace(
        _score_definition(),
        semester_selection_method="ALL",
        best_semester_count=None,
        weighting_mode="GRADE_ONLY",
        grade_weight_1=Decimal("0.40"),
        grade_weight_2=Decimal("0.60"),
    )


def _evidence(rule_kind: str, rule_id: str) -> ConsultationEvidence:
    return ConsultationEvidence(
        rule_kind=rule_kind,
        rule_id=rule_id,
        rule_version=DEMO_RULE_VERSION,
        source_document_id="demo-synthetic-document",
        document_type="DEMO_SYNTHETIC",
        document_status="DEMO_ONLY_NOT_OFFICIAL",
        page_number=1,
        locator="포트폴리오 합성 예시",
    )


def _course(course_id: str, name: str, credits: str, rank_grade: str) -> CourseRecordInput:
    return CourseRecordInput(
        course_record_id=course_id,
        subject_group="DEMO_GENERAL",
        subject_name=name,
        credits=Decimal(credits),
        raw_score=None,
        raw_score_label=None,
        course_mean=None,
        standard_deviation=None,
        achievement_level=None,
        enrollment_count=None,
        rank_grade=Decimal(rank_grade),
        user_verified=True,
    )


def _academic_records() -> tuple[AcademicRecordInput, ...]:
    grades = (
        (1, 1, ("2", "3")),
        (1, 2, ("1", "2")),
        (2, 1, ("3", "4")),
        (2, 2, ("2", "2")),
    )
    home_records = tuple(
        AcademicRecordInput(
            academic_record_id=f"demo-record-{grade}-{semester}",
            academic_year=2024 + grade,
            grade=grade,
            semester=semester,
            record_source="HOME_SCHOOL_RECORD",
            is_vocational_training_semester=False,
            verification_status="USER_VERIFIED",
            courses=(
                _course(f"demo-{grade}-{semester}-kor", "가상 국어", "3", values[0]),
                _course(f"demo-{grade}-{semester}-math", "가상 수학", "3", values[1]),
            ),
        )
        for grade, semester, values in grades
    )
    vocational = AcademicRecordInput(
        academic_record_id="demo-record-3-1-vocational",
        academic_year=2027,
        grade=3,
        semester=1,
        record_source="VOCATIONAL_TRAINING_RECORD",
        is_vocational_training_semester=True,
        verification_status="USER_VERIFIED",
        courses=(
            _course("demo-3-1-vocational-practice", "가상 전공실습", "4", "1"),
            _course("demo-3-1-vocational-theory", "가상 전공이론", "2", "2"),
        ),
    )
    return home_records + (vocational,)


def _score_definition() -> ScoreRuleDefinition:
    return ScoreRuleDefinition(
        home_grade_1_included=True,
        home_grade_2_included=True,
        home_grade_3_semester_1_included=False,
        home_grade_3_semester_2_included=False,
        vocational_grade_included=False,
        vocational_semester_1_included=False,
        vocational_semester_2_included=False,
        value_direction="LOWER_IS_BETTER",
        semester_selection_method="BEST_N",
        semester_selection_scope="GLOBAL",
        best_semester_count=2,
        subject_selection_method="ALL",
        best_subject_count=None,
        subject_scope="ALL",
        credit_weighted=True,
        minimum_semester_credits=None,
        semester_rounding_mode=None,
        semester_rounding_scale=None,
        grade_rounding_mode=None,
        grade_rounding_scale=None,
        grade_weight_1=None,
        grade_weight_2=None,
        grade_weight_3=None,
        semester_weight_1_1=None,
        semester_weight_1_2=None,
        semester_weight_2_1=None,
        semester_weight_2_2=None,
        semester_weight_3_1=None,
        semester_weight_3_2=None,
        weighting_mode="EQUAL",
        achievement_handling="EXCLUDE",
        achievement_table_code=None,
        achievement_source=None,
        achievement_formula_version=None,
        achievement_distribution_scale=None,
        career_subject_included=False,
        z_score_policy="NOT_USED",
        z_score_source=None,
        z_score_table_code=None,
        z_score_formula_version=None,
        z_score_rounding_mode=None,
        z_score_rounding_scale=None,
        z_score_clip_min=None,
        z_score_clip_max=None,
        attendance_included=False,
        attendance_table_code=None,
        attendance_source=None,
        attendance_minor_event_conversion_unit=None,
        interview_ratio=None,
        practical_ratio=None,
        rounding_mode="ROUND_HALF_UP",
        rounding_stage="FINAL",
        rounding_scale=2,
        display_scale=2,
        score_transform_mode="IDENTITY",
        score_base=None,
        score_multiplier=None,
        maximum_score=Decimal("9"),
    )


def _demo_admission_result() -> AdmissionResultComparison:
    result = AdmissionResultAnalysisInput(
        key=AdmissionResultKey(
            2026,
            "DEMO_SYNTHETIC_U",
            "DEMO_MAIN",
            "DEMO_EARLY_1",
            "DEMO_GENERAL",
            "DEMO_AI",
        ),
        publication_version="demo-synthetic-result-v1",
        applicant_count=120,
        admitted_count=40,
        competition_rate=Decimal("3.00"),
        highest_score=Decimal("1.25"),
        average_score=Decimal("2.70"),
        lowest_score=Decimal("4.10"),
        score_basis="DEMO_SYNTHETIC_RANK_GRADE",
        historical_rule=HistoricalRuleReference(
            rule_id="demo-synthetic-score-2026",
            version="demo-synthetic-2026-v1",
            academic_year=2026,
        ),
    )
    return AdmissionResultComparison(
        AdmissionResultComparisonStatus.REFERENCE_ONLY,
        result,
        "합성 예시이며 연도·규칙 버전이 달라 실제 합격 가능성 비교에 사용할 수 없습니다.",
    )


__all__ = [
    "DEMO_CONSULTATION_DEFAULTS",
    "DEMO_DEFAULT_PROGRAM_IDS",
    "DEMO_PROGRAMS",
    "DEMO_STUDENT_ID",
    "DEMO_TARGET",
    "DEMO_TRACK_ID",
    "demo_consultation_programs",
    "demo_consultation_targets",
    "run_demo_batch_consultation",
    "run_demo_consultation",
]
