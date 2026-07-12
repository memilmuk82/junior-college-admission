from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.services.eligibility import validate_eligibility_rule_payload
from app.services.score_inputs import validate_grade_source_scope_payload
from app.services.score_rule_schema import validate_score_rule_payload


class CandidateContractError(ValueError):
    pass


class CandidateGateStatus(StrEnum):
    MANUAL_REVIEW = "MANUAL_REVIEW"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    GOLDEN_PENDING = "GOLDEN_PENDING"
    HUMAN_APPROVAL_PENDING = "HUMAN_APPROVAL_PENDING"
    READY_FOR_PUBLISH = "READY_FOR_PUBLISH"


@dataclass(frozen=True)
class PilotRuleCandidate:
    admission_year: int
    university_code: str
    campus_code: str
    admission_round: str
    admission_track_code: str
    lifecycle_status: str
    evidence_level: str
    source_status: str
    source_document_id: str
    detected_years: tuple[int, ...]
    year_consistency_status: str
    eligibility_page: int | None
    grade_scope_page: int | None
    score_rule_page: int | None
    eligibility_payload: Mapping[str, object]
    grade_source_payload: dict[str, object]
    score_rule_payload: Mapping[str, object]
    independent_verified: bool
    golden_test_ref: str | None
    human_approved_at: datetime | None


@dataclass(frozen=True)
class CandidateGateResult:
    status: CandidateGateStatus
    blockers: tuple[str, ...]
    publish_allowed: bool


def evaluate_pilot_candidate(candidate: PilotRuleCandidate) -> CandidateGateResult:
    _validate_identity(candidate)
    if candidate.lifecycle_status == "PUBLISHED":
        raise CandidateContractError("후보 검증 서비스는 PUBLISHED 입력을 허용하지 않습니다.")
    if candidate.lifecycle_status not in {
        "DRAFT",
        "EXTRACTED",
        "VERIFIED",
        "TESTED",
        "HUMAN_APPROVED",
    }:
        raise CandidateContractError("허용되지 않은 파일럿 후보 생명주기입니다.")

    year_blockers = _year_blockers(candidate)
    if year_blockers:
        return CandidateGateResult(
            status=CandidateGateStatus.MANUAL_REVIEW,
            blockers=year_blockers,
            publish_allowed=False,
        )

    _validate_evidence(candidate)
    try:
        validate_eligibility_rule_payload(candidate.eligibility_payload)
        validate_grade_source_scope_payload(candidate.grade_source_payload)
        validate_score_rule_payload(candidate.score_rule_payload)
    except ValueError as error:
        raise CandidateContractError(f"파일럿 규칙 payload가 유효하지 않습니다: {error}") from error

    if candidate.lifecycle_status in {"VERIFIED", "TESTED", "HUMAN_APPROVED"} and not (
        candidate.independent_verified
    ):
        raise CandidateContractError("VERIFIED 이상 후보에는 독립 검증이 필요합니다.")
    if candidate.lifecycle_status in {"TESTED", "HUMAN_APPROVED"} and not (
        candidate.golden_test_ref
    ):
        raise CandidateContractError("TESTED 이상 후보에는 골든 테스트 참조가 필요합니다.")
    if candidate.lifecycle_status == "HUMAN_APPROVED" and candidate.human_approved_at is None:
        raise CandidateContractError("HUMAN_APPROVED 후보에는 사람 승인 시각이 필요합니다.")
    if candidate.human_approved_at is not None and candidate.lifecycle_status != "HUMAN_APPROVED":
        raise CandidateContractError("사람 승인 시각은 HUMAN_APPROVED 후보에만 기록할 수 있습니다.")

    if not candidate.independent_verified:
        return CandidateGateResult(
            CandidateGateStatus.VERIFICATION_PENDING,
            ("INDEPENDENT_VERIFICATION_REQUIRED",),
            False,
        )
    if not candidate.golden_test_ref:
        return CandidateGateResult(
            CandidateGateStatus.GOLDEN_PENDING,
            ("GOLDEN_TEST_REQUIRED",),
            False,
        )
    if candidate.human_approved_at is None:
        return CandidateGateResult(
            CandidateGateStatus.HUMAN_APPROVAL_PENDING,
            ("HUMAN_APPROVAL_REQUIRED",),
            False,
        )
    return CandidateGateResult(CandidateGateStatus.READY_FOR_PUBLISH, (), True)


def _validate_identity(candidate: PilotRuleCandidate) -> None:
    if candidate.admission_year < 2000:
        raise CandidateContractError("모집학년도가 허용 범위를 벗어났습니다.")
    required = (
        candidate.university_code,
        candidate.campus_code,
        candidate.admission_round,
        candidate.admission_track_code,
        candidate.source_document_id,
    )
    if any(not value.strip() for value in required):
        raise CandidateContractError("파일럿 업무키와 근거 문서 ID는 필수입니다.")


def _year_blockers(candidate: PilotRuleCandidate) -> tuple[str, ...]:
    blockers: list[str] = []
    if candidate.year_consistency_status != "CONSISTENT":
        blockers.append("MIXED_OR_UNCLEAR_YEAR")
    if candidate.detected_years != (candidate.admission_year,):
        blockers.append("DOCUMENT_YEAR_MISMATCH")
    return tuple(blockers)


def _validate_evidence(candidate: PilotRuleCandidate) -> None:
    if candidate.evidence_level != "UNIVERSITY_OFFICIAL":
        raise CandidateContractError("Phase 5 공식 파일럿 후보에는 대학 공식 근거가 필요합니다.")
    if candidate.source_status not in {
        "AMENDED_FINAL_GUIDE",
        "FINAL_GUIDE",
        "AMENDED_IMPLEMENTATION_PLAN",
        "IMPLEMENTATION_PLAN",
    }:
        raise CandidateContractError("파일럿 공식 후보의 문서 상태가 허용되지 않습니다.")
    pages = (
        candidate.eligibility_page,
        candidate.grade_scope_page,
        candidate.score_rule_page,
    )
    if any(page is None or page <= 0 for page in pages):
        raise CandidateContractError("자격·성적 범위·계산 규칙의 근거 쪽이 모두 필요합니다.")


__all__ = [
    "CandidateContractError",
    "CandidateGateResult",
    "CandidateGateStatus",
    "PilotRuleCandidate",
    "evaluate_pilot_candidate",
]
