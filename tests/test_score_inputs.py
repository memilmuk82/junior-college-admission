from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.services.eligibility import (
    EligibilityDecision,
    EligibilityStatus,
    EligibilityTrace,
    ScoreCalculationBlocked,
)
from app.services.published_rules import PublishedRule
from app.services.score_inputs import (
    AcademicRecordInput,
    CourseRecordInput,
    GradeSourcePolicy,
    ScoreInputStatus,
    evaluate_published_score_inputs,
    select_score_inputs,
    select_score_inputs_for_verification,
)


def _decision(status: EligibilityStatus) -> EligibilityDecision:
    return EligibilityDecision(
        status=status,
        reason_code="SYNTHETIC_ELIGIBILITY",
        matched_case_id="synthetic_case",
        missing_facts=(),
        trace=EligibilityTrace(
            rule_id="synthetic-eligibility-rule",
            rule_version="synthetic-v1",
            conditions=(),
        ),
    )


def _rule(policy: str) -> PublishedRule:
    from datetime import UTC, datetime

    return PublishedRule(
        rule_id="synthetic-scope-rule",
        admission_track_id="synthetic-track",
        version="synthetic-scope-v1",
        lifecycle_status="PUBLISHED",
        payload={"schema_version": 1, "policy": policy},
        source_citation_id="synthetic-citation",
        independent_verified=True,
        golden_test_ref="tests/test_score_inputs.py",
        human_approved_at=datetime(2026, 7, 12, tzinfo=UTC),
    )


def _course(
    course_id: str,
    subject: str,
    *,
    raw_score: Decimal | None = Decimal("90"),
    raw_score_label: str | None = None,
    verified: bool = True,
) -> CourseRecordInput:
    return CourseRecordInput(
        course_record_id=course_id,
        subject_group="합성 교과",
        subject_name=subject,
        credits=Decimal("3"),
        raw_score=raw_score,
        raw_score_label=raw_score_label,
        course_mean=Decimal("70"),
        standard_deviation=Decimal("10"),
        achievement_level="A",
        enrollment_count=100,
        rank_grade=Decimal("2"),
        user_verified=verified,
    )


def _records() -> tuple[AcademicRecordInput, ...]:
    return (
        AcademicRecordInput(
            academic_record_id="home-record",
            academic_year=2026,
            grade=2,
            semester=2,
            record_source="HOME_SCHOOL_RECORD",
            is_vocational_training_semester=False,
            verification_status="USER_VERIFIED",
            courses=(
                _course("home-course", "합성 원적교 과목"),
                _course("unverified-course", "합성 미검증 과목", verified=False),
            ),
        ),
        AcademicRecordInput(
            academic_record_id="vocational-record",
            academic_year=2026,
            grade=3,
            semester=1,
            record_source="VOCATIONAL_TRAINING_RECORD",
            is_vocational_training_semester=True,
            verification_status="USER_VERIFIED",
            courses=(
                _course(
                    "vocational-course",
                    "합성 위탁 과목",
                    raw_score=None,
                    raw_score_label="P",
                ),
            ),
        ),
    )


@pytest.mark.parametrize(
    ("policy", "expected_sources"),
    [
        (GradeSourcePolicy.HOME_ONLY, ("HOME_SCHOOL_RECORD",)),
        (
            GradeSourcePolicy.VOCATIONAL_INCLUDED,
            ("HOME_SCHOOL_RECORD", "VOCATIONAL_TRAINING_RECORD"),
        ),
        (GradeSourcePolicy.VOCATIONAL_ONLY, ("VOCATIONAL_TRAINING_RECORD",)),
        (
            GradeSourcePolicy.EXCLUDE_VOCATIONAL_SEMESTER,
            ("HOME_SCHOOL_RECORD",),
        ),
    ],
)
def test_source_scope_policies_keep_records_separate(
    policy: GradeSourcePolicy, expected_sources: tuple[str, ...]
) -> None:
    result = select_score_inputs(
        records=_records(),
        rule=_rule(policy.value),
        eligibility=_decision(EligibilityStatus.ELIGIBLE),
    )

    assert result.status is ScoreInputStatus.READY
    assert tuple(record.record_source for record in result.records) == expected_sources
    assert result.trace.selected_sources == expected_sources


def test_unverified_course_is_excluded_and_pass_label_is_preserved() -> None:
    result = select_score_inputs(
        records=_records(),
        rule=_rule("VOCATIONAL_INCLUDED"),
        eligibility=_decision(EligibilityStatus.CONDITIONALLY_ELIGIBLE),
    )

    selected_courses = [course for record in result.records for course in record.courses]
    assert [course.course_record_id for course in selected_courses] == [
        "home-course",
        "vocational-course",
    ]
    assert selected_courses[1].raw_score is None
    assert selected_courses[1].raw_score_label == "P"
    assert "COURSE_NOT_VERIFIED" in result.trace.exclusion_reasons


@pytest.mark.parametrize(
    "status",
    [
        EligibilityStatus.INELIGIBLE,
        EligibilityStatus.NEEDS_REVIEW,
        EligibilityStatus.INSUFFICIENT_DATA,
    ],
)
def test_eligibility_gate_blocks_before_scope_selection(status: EligibilityStatus) -> None:
    with pytest.raises(ScoreCalculationBlocked):
        select_score_inputs(
            records=_records(),
            rule=_rule("HOME_ONLY"),
            eligibility=_decision(status),
        )


@pytest.mark.parametrize("policy", ["TRACK_DEPENDENT", "MANUAL_REVIEW"])
def test_unresolved_scope_policies_require_review(policy: str) -> None:
    result = select_score_inputs(
        records=_records(),
        rule=_rule(policy),
        eligibility=_decision(EligibilityStatus.ELIGIBLE),
    )

    assert result.status is ScoreInputStatus.NEEDS_REVIEW
    assert result.records == ()


def test_empty_selected_scope_is_insufficient_data() -> None:
    result = select_score_inputs(
        records=(_records()[0],),
        rule=_rule("VOCATIONAL_ONLY"),
        eligibility=_decision(EligibilityStatus.ELIGIBLE),
    )

    assert result.status is ScoreInputStatus.INSUFFICIENT_DATA
    assert result.records == ()


def test_candidate_scope_can_be_selected_only_after_candidate_eligibility() -> None:
    result = select_score_inputs_for_verification(
        records=_records(),
        payload={"schema_version": 1, "policy": "EXCLUDE_VOCATIONAL_SEMESTER"},
        eligibility=_decision(EligibilityStatus.ELIGIBLE),
        rule_id="synthetic-candidate-scope",
        rule_version="candidate-v1",
    )

    assert result.status is ScoreInputStatus.READY
    assert result.trace.rule_version == "candidate-v1"
    assert result.trace.selected_sources == ("HOME_SCHOOL_RECORD",)


def test_candidate_scope_still_blocks_unconfirmed_eligibility() -> None:
    with pytest.raises(ScoreCalculationBlocked):
        select_score_inputs_for_verification(
            records=_records(),
            payload={"schema_version": 1, "policy": "HOME_ONLY"},
            eligibility=_decision(EligibilityStatus.NEEDS_REVIEW),
            rule_id="synthetic-candidate-scope",
            rule_version="candidate-v1",
        )


def test_scope_rule_rejects_unknown_policy_and_extra_fields() -> None:
    invalid = _rule("HOME_AND_GUESSED")
    invalid.payload["formula"] = "eval-me"

    with pytest.raises(ValueError):
        select_score_inputs(
            records=_records(),
            rule=invalid,
            eligibility=_decision(EligibilityStatus.ELIGIBLE),
        )


def test_published_scope_service_checks_eligibility_before_database_access() -> None:
    session = Session()
    try:
        with pytest.raises(ScoreCalculationBlocked):
            evaluate_published_score_inputs(
                session,
                "synthetic-track",
                "synthetic-student",
                _decision(EligibilityStatus.INELIGIBLE),
            )
    finally:
        session.close()
