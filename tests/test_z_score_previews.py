from decimal import Decimal

from app.services.consultations import _verified_course_values
from app.services.eligibility import (
    EligibilityRule,
    EligibilityStatus,
    StudentFacts,
    evaluate_eligibility_for_verification,
)
from app.services.score_inputs import (
    AcademicRecordInput,
    CourseRecordInput,
    GradeSourcePolicy,
    ScoreInputSelection,
    ScoreInputStatus,
    ScoreInputTrace,
)
from app.services.score_rule_schema import score_rule_definition_from_payload
from app.services.verified_source_rules import find_verified_source_rule
from app.services.z_score_previews import build_z_score_previews


def test_raw_z_preview_is_traceable_without_claiming_an_official_grade() -> None:
    preview = build_z_score_previews(
        ({"raw_score": "84", "course_mean": "74.5", "standard_deviation": "19.2"},)
    )[0]

    assert preview.status == "RAW_Z_READY"
    assert preview.raw_z_score == Decimal("9.5") / Decimal("19.2")
    assert preview.rounded_z_score == Decimal("0.49")
    assert "공식 변환표" in preview.message


def test_z_preview_never_invents_value_for_zero_or_missing_standard_deviation() -> None:
    previews = build_z_score_previews(
        (
            {"raw_score": "84", "course_mean": "74.5", "standard_deviation": "0"},
            {"raw_score": "84", "course_mean": "74.5", "standard_deviation": ""},
        )
    )

    assert all(item.status == "NEEDS_REVIEW" for item in previews)
    assert all(item.raw_z_score is None for item in previews)


def _selection() -> ScoreInputSelection:
    return ScoreInputSelection(
        status=ScoreInputStatus.READY,
        records=(
            AcademicRecordInput(
                academic_record_id="synthetic-term",
                academic_year=2026,
                grade=1,
                semester=1,
                record_source="HOME_SCHOOL_RECORD",
                is_vocational_training_semester=False,
                verification_status="USER_VERIFIED",
                courses=(
                    CourseRecordInput(
                        course_record_id="synthetic-z-course",
                        subject_group="국어",
                        subject_name="합성 Z 과목",
                        credits=Decimal("4"),
                        raw_score=Decimal("84"),
                        raw_score_label=None,
                        course_mean=Decimal("74.5"),
                        standard_deviation=Decimal("19.2"),
                        achievement_level=None,
                        enrollment_count=120,
                        rank_grade=None,
                        user_verified=True,
                    ),
                ),
            ),
        ),
        trace=ScoreInputTrace(
            rule_id="synthetic-scope",
            rule_version="v1",
            policy=GradeSourcePolicy.HOME_ONLY,
            selected_sources=("HOME_SCHOOL_RECORD",),
            selected_terms=(),
            exclusion_reasons=(),
        ),
    )


def test_inha_official_table_converts_missing_rank_grade_with_full_trace() -> None:
    rule = find_verified_source_rule(
        academic_year=2027,
        institution_code="INHA-TECHNICAL-COLLEGE",
        campus_code="MAIN",
        admission_round_code="SUSI-1",
        admission_track_code="SPECIAL-GENERAL-HS",
    )
    assert rule is not None

    values, missing, traces = _verified_course_values(
        _selection(),
        definition=score_rule_definition_from_payload(rule.score_rule_payload),
        rule=rule,
    )

    assert missing == ()
    assert values["synthetic-z-course"].normalized_value == Decimal("4")
    assert traces[0].rounded_z_score == Decimal("0.49")
    assert traces[0].table_code == "INHA_TECH_2027_Z_GRADE"
    assert traces[0].evidence_page == 10


def test_dongyang_does_not_invent_grade_without_supplied_full_official_table() -> None:
    rule = find_verified_source_rule(
        academic_year=2027,
        institution_code="DONGYANG-MIRAE",
        campus_code="MAIN",
        admission_round_code="SUSI-1",
        admission_track_code="SPECIAL-GENERAL-HS",
    )
    assert rule is not None

    values, missing, traces = _verified_course_values(
        _selection(),
        definition=score_rule_definition_from_payload(rule.score_rule_payload),
        rule=rule,
    )

    assert values == {}
    assert missing == ("synthetic-z-course",)
    assert traces == ()


def test_myongji_conservative_rule_allows_only_non_vocational_general_students() -> None:
    rule = find_verified_source_rule(
        academic_year=2027,
        institution_code="MYONGJI-COLLEGE",
        campus_code="MAIN",
        admission_round_code="SUSI-1",
        admission_track_code="SPECIAL-GENERAL-HS",
    )
    assert rule is not None
    eligibility_rule = EligibilityRule(
        rule_id=rule.rule_id,
        version=rule.version,
        lifecycle_status="VERIFIED",
        payload=rule.eligibility_payload,
        source_citation_id=rule.evidence["eligibility"].document_name,
        independent_verified=True,
        golden_test_ref=None,
        human_approved_at=None,
    )

    eligible = evaluate_eligibility_for_verification(
        StudentFacts(
            final_school_type="GENERAL",
            graduation_status="EXPECTED",
            vocational_training_status="NONE",
        ),
        eligibility_rule,
    )
    review = evaluate_eligibility_for_verification(
        StudentFacts(
            final_school_type="GENERAL",
            graduation_status="EXPECTED",
            vocational_training_status="PARTICIPATING",
        ),
        eligibility_rule,
    )

    assert eligible.status is EligibilityStatus.ELIGIBLE
    assert review.status is EligibilityStatus.NEEDS_REVIEW
    assert not review.allows_score_calculation
