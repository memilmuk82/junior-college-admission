from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from app.services.pilot_candidates import (
    CandidateContractError,
    CandidateGateStatus,
    PilotRuleCandidate,
    evaluate_pilot_candidate,
)
from app.services.score_rule_schema import parse_score_rule_csv, score_rule_to_payload
from tests.test_score_rule_schema import _csv_bytes, _valid_row


def _eligibility_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "cases": [
            {
                "case_id": "synthetic_general_high_school",
                "when": {"fact": "final_school_type", "op": "eq", "value": "GENERAL"},
                "status": "ELIGIBLE",
                "reason_code": "SYNTHETIC_ELIGIBLE",
            }
        ],
        "default": {
            "status": "NEEDS_REVIEW",
            "reason_code": "SYNTHETIC_REVIEW_REQUIRED",
        },
    }


def _candidate() -> PilotRuleCandidate:
    managed = parse_score_rule_csv(_csv_bytes([_valid_row()])).rows[0]
    return PilotRuleCandidate(
        admission_year=2027,
        university_code="SYNTHETIC_U",
        campus_code="MAIN",
        admission_round="EARLY_1",
        admission_track_code="GENERAL",
        lifecycle_status="EXTRACTED",
        evidence_level="UNIVERSITY_OFFICIAL",
        source_status="FINAL_GUIDE",
        source_document_id="synthetic-2027-guide",
        detected_years=(2027,),
        year_consistency_status="CONSISTENT",
        eligibility_page=10,
        grade_scope_page=11,
        score_rule_page=12,
        eligibility_payload=_eligibility_payload(),
        grade_source_payload={"schema_version": 1, "policy": "HOME_ONLY"},
        score_rule_payload=score_rule_to_payload(managed),
        independent_verified=False,
        golden_test_ref=None,
        human_approved_at=None,
    )


def test_official_extracted_candidate_waits_for_independent_verification() -> None:
    result = evaluate_pilot_candidate(_candidate())

    assert result.status is CandidateGateStatus.VERIFICATION_PENDING
    assert result.publish_allowed is False
    assert result.blockers == ("INDEPENDENT_VERIFICATION_REQUIRED",)


def test_mixed_year_candidate_remains_manual_review_without_rule_promotion() -> None:
    candidate = replace(
        _candidate(),
        detected_years=(2026, 2027),
        year_consistency_status="MIXED",
        eligibility_payload={},
        grade_source_payload={},
        score_rule_payload={},
    )

    result = evaluate_pilot_candidate(candidate)

    assert result.status is CandidateGateStatus.MANUAL_REVIEW
    assert "MIXED_OR_UNCLEAR_YEAR" in result.blockers
    assert result.publish_allowed is False


def test_candidate_lifecycle_cannot_overclaim_missing_review_or_golden() -> None:
    with pytest.raises(CandidateContractError):
        evaluate_pilot_candidate(replace(_candidate(), lifecycle_status="VERIFIED"))

    with pytest.raises(CandidateContractError):
        evaluate_pilot_candidate(
            replace(
                _candidate(),
                lifecycle_status="TESTED",
                independent_verified=True,
            )
        )


def test_candidate_service_never_accepts_published_input() -> None:
    with pytest.raises(CandidateContractError):
        evaluate_pilot_candidate(
            replace(
                _candidate(),
                lifecycle_status="PUBLISHED",
                independent_verified=True,
                golden_test_ref="tests/synthetic-golden",
                human_approved_at=datetime(2026, 7, 12, tzinfo=UTC),
            )
        )


def test_human_approved_candidate_is_only_ready_for_separate_publish_action() -> None:
    candidate = replace(
        _candidate(),
        lifecycle_status="HUMAN_APPROVED",
        independent_verified=True,
        golden_test_ref="tests/synthetic-golden",
        human_approved_at=datetime(2026, 7, 12, tzinfo=UTC),
    )

    result = evaluate_pilot_candidate(candidate)

    assert result.status is CandidateGateStatus.READY_FOR_PUBLISH
    assert result.publish_allowed is True
    assert candidate.lifecycle_status == "HUMAN_APPROVED"
