from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.application_policies import (
    ApplicationChoice,
    ApplicationHistory,
    DisqualificationStatus,
    MultipleApplicationStatus,
    PolicySchemaError,
    SensitiveDisqualificationFacts,
    evaluate_disqualification,
    evaluate_multiple_application,
)
from app.services.consultation_forms import parse_consultation_form
from app.services.demo_consultations import (
    DEMO_CONSULTATION_DEFAULTS,
    run_demo_consultation,
)
from app.services.published_rules import PublishedRule


def _published_rule(payload: dict[str, object]) -> PublishedRule:
    return PublishedRule(
        rule_id="synthetic-policy-rule",
        admission_track_id="synthetic-candidate-track",
        version="synthetic-v1",
        lifecycle_status="PUBLISHED",
        payload=payload,
        source_citation_id="synthetic-citation",
        independent_verified=True,
        golden_test_ref="tests/test_application_policies.py",
        human_approved_at=datetime(2026, 7, 12, tzinfo=UTC),
    )


def _multiple_rule(
    *,
    total: int | None = None,
    per_campus: int | None = None,
    forbidden: list[list[str]] | None = None,
) -> PublishedRule:
    return _published_rule(
        {
            "schema_version": 1,
            "limits": {"total": total, "per_campus": per_campus},
            "forbidden_track_combinations": forbidden or [],
            "reason_codes": {
                "allowed": "SYNTHETIC_ALLOWED",
                "history_incomplete": "SYNTHETIC_HISTORY_INCOMPLETE",
                "max_applications": "SYNTHETIC_MAX_APPLICATIONS",
                "max_per_campus": "SYNTHETIC_MAX_PER_CAMPUS",
                "forbidden_combination": "SYNTHETIC_FORBIDDEN_COMBINATION",
            },
        }
    )


def _candidate() -> ApplicationChoice:
    return ApplicationChoice(
        track_id="synthetic-candidate-track",
        institution_id="synthetic-institution",
        campus_id="synthetic-campus-a",
    )


def test_multiple_application_limits_are_separate_from_eligibility() -> None:
    decision = evaluate_multiple_application(
        candidate=_candidate(),
        history=ApplicationHistory(
            choices=(
                ApplicationChoice(
                    track_id="synthetic-existing-track",
                    institution_id="synthetic-institution",
                    campus_id="synthetic-campus-b",
                ),
            ),
            is_complete=True,
        ),
        rule=_multiple_rule(total=1),
    )

    assert decision.status is MultipleApplicationStatus.BLOCKED
    assert decision.reason_code == "SYNTHETIC_MAX_APPLICATIONS"
    assert decision.trace.matched_constraint == "max_applications"


def test_per_campus_limit_and_forbidden_combination_are_data_driven() -> None:
    existing = ApplicationChoice(
        track_id="synthetic-existing-track",
        institution_id="synthetic-institution",
        campus_id="synthetic-campus-a",
    )
    history = ApplicationHistory(choices=(existing,), is_complete=True)

    campus_decision = evaluate_multiple_application(
        candidate=_candidate(),
        history=history,
        rule=_multiple_rule(per_campus=1),
    )
    combination_decision = evaluate_multiple_application(
        candidate=_candidate(),
        history=history,
        rule=_multiple_rule(
            forbidden=[
                ["synthetic-existing-track", "synthetic-candidate-track"],
            ]
        ),
    )

    assert campus_decision.status is MultipleApplicationStatus.BLOCKED
    assert campus_decision.trace.matched_constraint == "max_per_campus"
    assert combination_decision.status is MultipleApplicationStatus.BLOCKED
    assert combination_decision.trace.matched_constraint == "forbidden_combination"


def test_incomplete_application_history_requires_review_instead_of_guessing() -> None:
    decision = evaluate_multiple_application(
        candidate=_candidate(),
        history=ApplicationHistory(choices=(), is_complete=False),
        rule=_multiple_rule(total=1),
    )

    assert decision.status is MultipleApplicationStatus.NEEDS_REVIEW
    assert decision.reason_code == "SYNTHETIC_HISTORY_INCOMPLETE"


def test_multiple_application_rule_allows_when_no_constraint_matches() -> None:
    decision = evaluate_multiple_application(
        candidate=_candidate(),
        history=ApplicationHistory(choices=(), is_complete=True),
        rule=_multiple_rule(total=2, per_campus=1),
    )

    assert decision.status is MultipleApplicationStatus.ALLOWED
    assert decision.trace.matched_constraint is None


@pytest.mark.parametrize(
    "limits",
    [
        {"total": 0, "per_campus": None},
        {"total": None, "per_campus": -1},
        {"total": "2", "per_campus": None},
    ],
)
def test_invalid_multiple_application_limits_are_rejected(
    limits: dict[str, object],
) -> None:
    payload = dict(_multiple_rule().payload)
    payload["limits"] = limits

    with pytest.raises(PolicySchemaError):
        evaluate_multiple_application(
            candidate=_candidate(),
            history=ApplicationHistory(choices=(), is_complete=True),
            rule=_published_rule(payload),
        )


def _disqualification_rule(
    *, status: str = "INELIGIBLE", default_status: str = "ELIGIBLE"
) -> PublishedRule:
    return _published_rule(
        {
            "schema_version": 1,
            "cases": [
                {
                    "case_id": "synthetic_sensitive_condition",
                    "when": {
                        "fact": "additional.disqualifying_condition_confirmed",
                        "op": "is_true",
                    },
                    "status": status,
                    "reason_code": "SYNTHETIC_DISQUALIFICATION",
                }
            ],
            "default": {
                "status": default_status,
                "reason_code": "SYNTHETIC_CLEAR",
            },
        }
    )


def test_sensitive_disqualification_is_evaluated_without_value_in_trace() -> None:
    decision = evaluate_disqualification(
        facts=SensitiveDisqualificationFacts({"disqualifying_condition_confirmed": True}),
        rule=_disqualification_rule(),
    )

    assert decision.status is DisqualificationStatus.DISQUALIFIED
    assert decision.trace.conditions[0].fact == ("additional.disqualifying_condition_confirmed")
    assert not hasattr(decision.trace.conditions[0], "actual_value")


def test_missing_sensitive_fact_is_not_assumed_clear_or_disqualified() -> None:
    decision = evaluate_disqualification(
        facts=SensitiveDisqualificationFacts({}),
        rule=_disqualification_rule(),
    )

    assert decision.status is DisqualificationStatus.INSUFFICIENT_DATA
    assert decision.missing_facts == ("additional.disqualifying_condition_confirmed",)


def test_false_sensitive_fact_is_clear_and_review_case_stays_separate() -> None:
    clear = evaluate_disqualification(
        facts=SensitiveDisqualificationFacts({"disqualifying_condition_confirmed": False}),
        rule=_disqualification_rule(),
    )
    review = evaluate_disqualification(
        facts=SensitiveDisqualificationFacts({"disqualifying_condition_confirmed": True}),
        rule=_disqualification_rule(status="NEEDS_REVIEW"),
    )

    assert clear.status is DisqualificationStatus.CLEAR
    assert review.status is DisqualificationStatus.NEEDS_REVIEW


@pytest.mark.parametrize(
    "payload",
    [
        {
            "schema_version": 1,
            "cases": [
                {
                    "case_id": "invalid_base_fact",
                    "when": {"fact": "ged", "op": "is_true"},
                    "status": "INELIGIBLE",
                    "reason_code": "SYNTHETIC_INVALID",
                }
            ],
            "default": {"status": "ELIGIBLE", "reason_code": "SYNTHETIC_CLEAR"},
        },
        {
            "schema_version": 1,
            "cases": [
                {
                    "case_id": "invalid_status",
                    "when": {"fact": "additional.flag", "op": "is_true"},
                    "status": "CONDITIONALLY_ELIGIBLE",
                    "reason_code": "SYNTHETIC_INVALID",
                }
            ],
            "default": {"status": "ELIGIBLE", "reason_code": "SYNTHETIC_CLEAR"},
        },
    ],
)
def test_disqualification_rules_reject_eligibility_facts_and_statuses(
    payload: dict[str, object],
) -> None:
    with pytest.raises(PolicySchemaError):
        evaluate_disqualification(
            facts=SensitiveDisqualificationFacts({"flag": True}),
            rule=_published_rule(payload),
        )


def test_synthetic_demo_reuses_eligibility_first_and_score_engines_without_database() -> None:
    eligible_form = parse_consultation_form(DEMO_CONSULTATION_DEFAULTS)
    assert eligible_form.request is not None
    eligible = run_demo_consultation(eligible_form.request)

    assert eligible.status.value == "READY"
    assert eligible.eligibility.reason_code == "DEMO_GENERAL_ALLOWED"
    assert eligible.score is not None
    assert str(eligible.score.display_score) == "1.75"
    assert eligible.admission_result.result is not None
    assert str(eligible.admission_result.result.competition_rate) == "3.00"

    blocked_values = {**DEMO_CONSULTATION_DEFAULTS, "final_school_type": "VOCATIONAL"}
    blocked_form = parse_consultation_form(blocked_values)
    assert blocked_form.request is not None
    blocked = run_demo_consultation(blocked_form.request)

    assert blocked.status.value == "ELIGIBILITY_BLOCKED"
    assert blocked.score is None
    assert blocked.score_input is None
