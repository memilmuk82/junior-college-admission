from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.services.consultations import (
    AdmissionResultComparisonStatus,
    ConsultationResult,
)

ANONYMOUS_PAYLOAD_SCHEMA_VERSION = 1
TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "consultation_status",
        "target",
        "eligibility",
        "score",
        "admission_result",
        "evidence",
    }
)
TARGET_KEYS = frozenset(
    {
        "academic_year",
        "institution_name",
        "campus_name",
        "program_name",
        "admission_round_name",
        "admission_track_name",
    }
)
ELIGIBILITY_KEYS = frozenset({"status", "reason_code", "missing_fact_names", "rule_version"})
SCORE_KEYS = frozenset(
    {
        "final_score",
        "display_score",
        "maximum_score",
        "rule_version",
        "rounding_mode",
        "rounding_scale",
        "non_predictive_components",
    }
)
ADMISSION_RESULT_KEYS = frozenset(
    {
        "status",
        "academic_year",
        "applicant_count",
        "admitted_count",
        "competition_rate",
        "highest_score",
        "average_score",
        "lowest_score",
        "score_basis",
        "publication_version",
    }
)
EVIDENCE_KEYS = frozenset(
    {"rule_kind", "rule_version", "document_type", "document_status", "page_number"}
)


@dataclass(frozen=True)
class AnonymousConsultationPayload:
    schema_version: int
    data: dict[str, Any]
    canonical_json: str
    digest: str


def build_anonymous_consultation_payload(
    result: ConsultationResult,
) -> AnonymousConsultationPayload:
    data: dict[str, Any] = {
        "schema_version": ANONYMOUS_PAYLOAD_SCHEMA_VERSION,
        "consultation_status": result.status.value,
        "target": {
            "academic_year": result.target.academic_year,
            "institution_name": result.target.institution_name,
            "campus_name": result.target.campus_name,
            "program_name": result.target.program_name,
            "admission_round_name": result.target.admission_round_name,
            "admission_track_name": result.target.admission_track_name,
        },
        "eligibility": {
            "status": result.eligibility.status.value,
            "reason_code": result.eligibility.reason_code,
            "missing_fact_names": list(result.eligibility.missing_facts),
            "rule_version": result.eligibility.trace.rule_version,
        },
        "score": _score_payload(result),
        "admission_result": _admission_result_payload(result),
        "evidence": [
            {
                "rule_kind": item.rule_kind,
                "rule_version": item.rule_version,
                "document_type": item.document_type,
                "document_status": item.document_status,
                "page_number": item.page_number,
            }
            for item in result.evidence
        ],
    }
    canonical_json = json.dumps(
        data,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return AnonymousConsultationPayload(
        schema_version=ANONYMOUS_PAYLOAD_SCHEMA_VERSION,
        data=data,
        canonical_json=canonical_json,
        digest=hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
    )


def validated_payload_copy(payload: AnonymousConsultationPayload) -> dict[str, Any]:
    if payload.schema_version != ANONYMOUS_PAYLOAD_SCHEMA_VERSION:
        raise ValueError("지원하지 않는 AI payload schema version입니다.")
    expected_digest = hashlib.sha256(payload.canonical_json.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(expected_digest, payload.digest):
        raise ValueError("AI payload digest가 canonical JSON과 다릅니다.")
    try:
        parsed = json.loads(payload.canonical_json)
    except json.JSONDecodeError as error:
        raise ValueError("AI payload canonical JSON이 유효하지 않습니다.") from error
    if not isinstance(parsed, dict) or parsed != payload.data:
        raise ValueError("AI payload data가 canonical JSON과 다릅니다.")
    canonical = json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if not hmac.compare_digest(canonical.encode("utf-8"), payload.canonical_json.encode("utf-8")):
        raise ValueError("AI payload JSON이 canonical 형식이 아닙니다.")
    _validate_payload_keys(parsed)
    return parsed


def _validate_payload_keys(data: dict[str, Any]) -> None:
    if frozenset(data) != TOP_LEVEL_KEYS or data.get("schema_version") != 1:
        raise ValueError("AI payload 최상위 필드가 고정 schema와 다릅니다.")
    _require_exact_keys(data.get("target"), TARGET_KEYS, "target")
    _require_exact_keys(data.get("eligibility"), ELIGIBILITY_KEYS, "eligibility")
    score = data.get("score")
    if score is not None:
        _require_exact_keys(score, SCORE_KEYS, "score")
    admission_result = data.get("admission_result")
    if not isinstance(admission_result, dict):
        raise ValueError("AI payload admission_result가 객체가 아닙니다.")
    admission_keys = frozenset(admission_result)
    if admission_keys not in {frozenset({"status"}), ADMISSION_RESULT_KEYS}:
        raise ValueError("AI payload admission_result 필드가 고정 schema와 다릅니다.")
    evidence = data.get("evidence")
    if not isinstance(evidence, list):
        raise ValueError("AI payload evidence가 배열이 아닙니다.")
    for item in evidence:
        _require_exact_keys(item, EVIDENCE_KEYS, "evidence")


def _require_exact_keys(value: object, allowed: frozenset[str], field: str) -> None:
    if not isinstance(value, dict) or frozenset(value) != allowed:
        raise ValueError(f"AI payload {field} 필드가 고정 schema와 다릅니다.")


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _score_payload(result: ConsultationResult) -> dict[str, Any] | None:
    if result.score is None:
        return None
    return {
        "final_score": _decimal(result.score.final_score),
        "display_score": _decimal(result.score.display_score),
        "maximum_score": _decimal(result.score.maximum_score),
        "rule_version": result.score.trace.rule_version,
        "rounding_mode": result.score.trace.rounding_mode,
        "rounding_scale": result.score.trace.rounding_scale,
        "non_predictive_components": {
            name: _decimal(value) for name, value in result.score.trace.non_predictive_components
        },
    }


def _admission_result_payload(result: ConsultationResult) -> dict[str, Any]:
    comparison = result.admission_result
    base: dict[str, Any] = {"status": comparison.status.value}
    if (
        comparison.status is not AdmissionResultComparisonStatus.COMPARABLE
        or comparison.result is None
    ):
        return base
    published = comparison.result
    return base | {
        "academic_year": published.key.academic_year,
        "applicant_count": published.applicant_count,
        "admitted_count": published.admitted_count,
        "competition_rate": _decimal(published.competition_rate),
        "highest_score": _decimal(published.highest_score),
        "average_score": _decimal(published.average_score),
        "lowest_score": _decimal(published.lowest_score),
        "score_basis": published.score_basis,
        "publication_version": published.publication_version,
    }


__all__ = [
    "ANONYMOUS_PAYLOAD_SCHEMA_VERSION",
    "AnonymousConsultationPayload",
    "build_anonymous_consultation_payload",
    "validated_payload_copy",
]
