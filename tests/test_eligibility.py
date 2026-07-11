from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.eligibility import (
    EligibilityRule,
    EligibilityStatus,
    RuleSchemaError,
    ScoreCalculationBlocked,
    StudentFacts,
    UnusableEligibilityRule,
    evaluate_eligibility,
    require_score_calculation_allowed,
)


def _rule(
    cases: list[dict[str, object]],
    *,
    default_status: str = "INELIGIBLE",
    lifecycle_status: str = "PUBLISHED",
) -> EligibilityRule:
    return EligibilityRule(
        rule_id="synthetic-rule",
        version="synthetic-v1",
        lifecycle_status=lifecycle_status,
        source_citation_id="synthetic-citation",
        independent_verified=True,
        golden_test_ref="tests/test_eligibility.py",
        human_approved_at=datetime(2026, 7, 12, tzinfo=UTC),
        payload={
            "schema_version": 1,
            "cases": cases,
            "default": {
                "status": default_status,
                "reason_code": "SYNTHETIC_DEFAULT",
            },
        },
    )


def _general_vocational_student() -> StudentFacts:
    return StudentFacts(
        home_school_type="GENERAL",
        final_school_type="GENERAL",
        graduation_status="EXPECTED",
        vocational_training_status="EXPECTED_COMPLETION",
        vocational_training_semesters=2,
        vocational_training_hours=800,
        vocational_training_months=10,
        transferred=False,
        ged=False,
    )


def test_same_student_is_evaluated_independently_for_each_track() -> None:
    facts = _general_vocational_student()
    general_track = _rule(
        [
            {
                "case_id": "general_school",
                "when": {"fact": "final_school_type", "op": "eq", "value": "GENERAL"},
                "status": "ELIGIBLE",
                "reason_code": "SYNTHETIC_GENERAL_ALLOWED",
            }
        ]
    )
    vocational_track = _rule(
        [
            {
                "case_id": "vocational_graduate_only",
                "when": {
                    "fact": "final_school_type",
                    "op": "eq",
                    "value": "VOCATIONAL",
                },
                "status": "ELIGIBLE",
                "reason_code": "SYNTHETIC_VOCATIONAL_ONLY",
            }
        ]
    )

    assert evaluate_eligibility(facts, general_track).status is EligibilityStatus.ELIGIBLE
    assert evaluate_eligibility(facts, vocational_track).status is EligibilityStatus.INELIGIBLE


def test_general_and_vocational_tracks_can_both_be_eligible() -> None:
    facts = _general_vocational_student()
    general_track = _rule(
        [
            {
                "case_id": "home_school",
                "when": {"fact": "home_school_type", "op": "eq", "value": "GENERAL"},
                "status": "ELIGIBLE",
                "reason_code": "SYNTHETIC_HOME_SCHOOL",
            }
        ]
    )
    vocational_track = _rule(
        [
            {
                "case_id": "training",
                "when": {
                    "all": [
                        {
                            "fact": "vocational_training_status",
                            "op": "in",
                            "value": ["EXPECTED_COMPLETION", "COMPLETED"],
                        },
                        {
                            "fact": "vocational_training_hours",
                            "op": "gte",
                            "value": 600,
                        },
                    ]
                },
                "status": "CONDITIONALLY_ELIGIBLE",
                "reason_code": "SYNTHETIC_TRAINING_ALLOWED",
            }
        ]
    )

    decisions = [
        evaluate_eligibility(facts, general_track),
        evaluate_eligibility(facts, vocational_track),
    ]

    assert [decision.status for decision in decisions] == [
        EligibilityStatus.ELIGIBLE,
        EligibilityStatus.CONDITIONALLY_ELIGIBLE,
    ]


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (StudentFacts(final_school_type="MEISTER"), EligibilityStatus.ELIGIBLE),
        (StudentFacts(final_school_type="COMPREHENSIVE_VOCATIONAL"), EligibilityStatus.ELIGIBLE),
        (StudentFacts(ged=True), EligibilityStatus.ELIGIBLE),
    ],
)
def test_school_types_and_ged_are_data_driven(
    facts: StudentFacts, expected: EligibilityStatus
) -> None:
    rule = _rule(
        [
            {
                "case_id": "school_or_ged",
                "when": {
                    "any": [
                        {
                            "fact": "final_school_type",
                            "op": "in",
                            "value": ["MEISTER", "COMPREHENSIVE_VOCATIONAL"],
                        },
                        {"fact": "ged", "op": "is_true"},
                    ]
                },
                "status": "ELIGIBLE",
                "reason_code": "SYNTHETIC_SCHOOL_OR_GED",
            }
        ]
    )

    assert evaluate_eligibility(facts, rule).status is expected


def test_program_exception_uses_bounded_additional_fact() -> None:
    facts = StudentFacts(additional={"program_exception_met": True})
    rule = _rule(
        [
            {
                "case_id": "program_exception",
                "when": {"fact": "additional.program_exception_met", "op": "is_true"},
                "status": "ELIGIBLE",
                "reason_code": "SYNTHETIC_PROGRAM_EXCEPTION",
            }
        ]
    )

    decision = evaluate_eligibility(facts, rule)

    assert decision.status is EligibilityStatus.ELIGIBLE
    assert decision.matched_case_id == "program_exception"


def test_missing_fact_is_insufficient_data_not_ineligible() -> None:
    rule = _rule(
        [
            {
                "case_id": "graduation",
                "when": {
                    "fact": "graduation_status",
                    "op": "in",
                    "value": ["EXPECTED", "GRADUATED"],
                },
                "status": "ELIGIBLE",
                "reason_code": "SYNTHETIC_GRADUATION",
            }
        ]
    )

    decision = evaluate_eligibility(StudentFacts(), rule)

    assert decision.status is EligibilityStatus.INSUFFICIENT_DATA
    assert decision.missing_facts == ("graduation_status",)


def test_explicit_review_case_is_not_exposed_as_confirmed() -> None:
    rule = _rule(
        [
            {
                "case_id": "foreign_school_review",
                "when": {"fact": "final_school_type", "op": "eq", "value": "FOREIGN"},
                "status": "NEEDS_REVIEW",
                "reason_code": "SYNTHETIC_FOREIGN_REVIEW",
            }
        ]
    )

    decision = evaluate_eligibility(StudentFacts(final_school_type="FOREIGN"), rule)

    assert decision.status is EligibilityStatus.NEEDS_REVIEW
    assert not decision.is_confirmed


@pytest.mark.parametrize(
    "condition",
    [
        {"expression": "student.school == 'GENERAL'"},
        {"fact": "student_name", "op": "eq", "value": "synthetic"},
        {"fact": "final_school_type", "op": "exec", "value": "GENERAL"},
        {"fact": "additional.invalid-key", "op": "is_true"},
        {"fact": "final_school_type", "op": "eq", "value": "GENERAL_TYPO"},
        {"fact": "vocational_training_hours", "op": "eq", "value": "600"},
        {"fact": "ged", "op": "eq", "value": "true"},
    ],
)
def test_unbounded_conditions_are_rejected(condition: dict[str, object]) -> None:
    rule = _rule(
        [
            {
                "case_id": "invalid",
                "when": condition,
                "status": "ELIGIBLE",
                "reason_code": "SYNTHETIC_INVALID",
            }
        ]
    )

    with pytest.raises(RuleSchemaError):
        evaluate_eligibility(StudentFacts(), rule)


@pytest.mark.parametrize("lifecycle_status", ["DRAFT", "VERIFIED", "HUMAN_APPROVED"])
def test_non_published_rules_cannot_run(lifecycle_status: str) -> None:
    with pytest.raises(UnusableEligibilityRule):
        evaluate_eligibility(StudentFacts(), _rule([], lifecycle_status=lifecycle_status))


def test_published_rule_without_complete_evidence_cannot_run() -> None:
    rule = _rule([])
    rule_without_evidence = EligibilityRule(
        rule_id=rule.rule_id,
        version=rule.version,
        lifecycle_status=rule.lifecycle_status,
        payload=rule.payload,
        source_citation_id=None,
        independent_verified=False,
        golden_test_ref=None,
        human_approved_at=None,
    )

    with pytest.raises(UnusableEligibilityRule):
        evaluate_eligibility(StudentFacts(), rule_without_evidence)


def test_definite_false_in_all_condition_does_not_become_insufficient() -> None:
    rule = _rule(
        [
            {
                "case_id": "general_graduate",
                "when": {
                    "all": [
                        {
                            "fact": "final_school_type",
                            "op": "eq",
                            "value": "GENERAL",
                        },
                        {
                            "fact": "graduation_status",
                            "op": "eq",
                            "value": "GRADUATED",
                        },
                    ]
                },
                "status": "ELIGIBLE",
                "reason_code": "SYNTHETIC_GENERAL_GRADUATE",
            }
        ]
    )

    decision = evaluate_eligibility(StudentFacts(final_school_type="VOCATIONAL"), rule)

    assert decision.status is EligibilityStatus.INELIGIBLE
    assert decision.missing_facts == ()


def test_not_preserves_unknown_and_inverts_known_condition() -> None:
    rule = _rule(
        [
            {
                "case_id": "not_ged",
                "when": {"not": {"fact": "ged", "op": "is_true"}},
                "status": "ELIGIBLE",
                "reason_code": "SYNTHETIC_NOT_GED",
            }
        ]
    )

    assert evaluate_eligibility(StudentFacts(), rule).status is EligibilityStatus.INSUFFICIENT_DATA
    assert evaluate_eligibility(StudentFacts(ged=False), rule).status is EligibilityStatus.ELIGIBLE
    assert evaluate_eligibility(StudentFacts(ged=True), rule).status is EligibilityStatus.INELIGIBLE


def test_trace_is_reproducible_and_does_not_include_actual_values() -> None:
    facts = _general_vocational_student()
    rule = _rule(
        [
            {
                "case_id": "general_school",
                "when": {"fact": "final_school_type", "op": "eq", "value": "GENERAL"},
                "status": "ELIGIBLE",
                "reason_code": "SYNTHETIC_GENERAL_ALLOWED",
            }
        ]
    )

    first = evaluate_eligibility(facts, rule)
    second = evaluate_eligibility(facts, rule)

    assert first.trace == second.trace
    assert first.trace.rule_id == "synthetic-rule"
    assert first.trace.rule_version == "synthetic-v1"
    assert first.trace.conditions[0].fact == "final_school_type"
    assert not hasattr(first.trace.conditions[0], "actual_value")


@pytest.mark.parametrize(
    "status",
    [
        EligibilityStatus.INELIGIBLE,
        EligibilityStatus.NEEDS_REVIEW,
        EligibilityStatus.INSUFFICIENT_DATA,
    ],
)
def test_score_calculation_is_blocked_before_entry(status: EligibilityStatus) -> None:
    decision = evaluate_eligibility(
        StudentFacts(final_school_type="GENERAL"),
        _rule(
            [
                {
                    "case_id": "status",
                    "when": {
                        "fact": "final_school_type",
                        "op": "eq",
                        "value": "GENERAL",
                    },
                    "status": status.value,
                    "reason_code": "SYNTHETIC_STATUS",
                }
            ]
        ),
    )

    with pytest.raises(ScoreCalculationBlocked):
        require_score_calculation_allowed(decision)


@pytest.mark.parametrize(
    "status", [EligibilityStatus.ELIGIBLE, EligibilityStatus.CONDITIONALLY_ELIGIBLE]
)
def test_score_calculation_gate_allows_eligible_statuses(status: EligibilityStatus) -> None:
    decision = evaluate_eligibility(
        StudentFacts(ged=True),
        _rule(
            [
                {
                    "case_id": "allowed",
                    "when": {"fact": "ged", "op": "is_true"},
                    "status": status.value,
                    "reason_code": "SYNTHETIC_ALLOWED",
                }
            ]
        ),
    )

    require_score_calculation_allowed(decision)
