from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.services.consultations import BatchConsultationResult, ConsultationResult

ANONYMOUS_PAYLOAD_SCHEMA_VERSION = 2
TOP_LEVEL_KEYS = frozenset({"schema_version", "academic_year", "results"})
RESULT_KEYS = frozenset(
    {
        "item_status",
        "target",
        "eligibility",
        "average_grade",
        "admission_result",
        "evidence",
        "warnings",
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
AVERAGE_GRADE_KEYS = frozenset(
    {
        "unrounded_average_grade",
        "final_average_grade",
        "display_average_grade",
        "grade_scale",
        "rule_version",
        "weighting_mode",
        "rounding_mode",
        "rounding_scale",
    }
)
ADMISSION_RESULT_KEYS = frozenset(
    {
        "status",
        "academic_year",
        "competition_rate",
        "average_grade",
        "score_basis",
        "publication_version",
    }
)
EVIDENCE_KEYS = frozenset(
    {
        "rule_kind",
        "rule_version",
        "source_document_id",
        "document_type",
        "document_status",
        "page_number",
        "locator",
    }
)


@dataclass(frozen=True)
class AnonymousConsultationPayload:
    schema_version: int
    data: dict[str, Any]
    canonical_json: str
    digest: str


def build_anonymous_consultation_payload(
    result: ConsultationResult | BatchConsultationResult,
) -> AnonymousConsultationPayload:
    if isinstance(result, BatchConsultationResult):
        academic_year = result.academic_year
        rows = [_batch_item_payload(item) for item in result.items]
    else:
        academic_year = result.target.academic_year
        rows = [_consultation_result_payload(result)]
    data: dict[str, Any] = {
        "schema_version": ANONYMOUS_PAYLOAD_SCHEMA_VERSION,
        "academic_year": academic_year,
        "results": rows,
    }
    canonical_json = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return AnonymousConsultationPayload(
        ANONYMOUS_PAYLOAD_SCHEMA_VERSION,
        data,
        canonical_json,
        hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
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
    if not hmac.compare_digest(canonical.encode(), payload.canonical_json.encode()):
        raise ValueError("AI payload JSON이 canonical 형식이 아닙니다.")
    _validate_payload_keys(parsed)
    return parsed


def validated_saved_payload_copy(data: object) -> dict[str, Any]:
    """Return a JSON-only, schema-complete copy suitable for durable SSR snapshots."""
    if not isinstance(data, dict):
        raise ValueError("저장 상담 payload는 객체여야 합니다.")
    _validate_payload_keys(data)
    if not isinstance(data.get("academic_year"), int):
        raise ValueError("저장 상담 payload의 학년도가 유효하지 않습니다.")
    for row in data["results"]:
        if not isinstance(row["item_status"], str):
            raise ValueError("저장 상담 결과 상태가 유효하지 않습니다.")
        if not all(isinstance(value, str) for value in row["warnings"]):
            raise ValueError("저장 상담 경고는 문자열 배열이어야 합니다.")
    try:
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        copied = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("저장 상담 payload는 JSON으로 직렬화할 수 있어야 합니다.") from error
    assert isinstance(copied, dict)
    return copied


def _batch_item_payload(item: Any) -> dict[str, Any]:
    if item.result is not None:
        return _consultation_result_payload(item.result)
    target = None
    if item.target is not None:
        target = _target_payload(item.target)
    else:
        target = {
            "academic_year": item.program.academic_year,
            "institution_name": item.program.institution_name,
            "campus_name": item.program.campus_name,
            "program_name": item.program.program_name,
            "admission_round_name": None,
            "admission_track_name": None,
        }
    return {
        "item_status": item.status.value,
        "target": target,
        "eligibility": None,
        "average_grade": None,
        "admission_result": {"status": "NOT_AVAILABLE"},
        "evidence": [],
        "warnings": [f"ITEM_{item.status.value}"],
    }


def _consultation_result_payload(result: ConsultationResult) -> dict[str, Any]:
    return {
        "item_status": result.status.value,
        "target": _target_payload(result.target),
        "eligibility": {
            "status": result.eligibility.status.value,
            "reason_code": result.eligibility.reason_code,
            "missing_fact_names": list(result.eligibility.missing_facts),
            "rule_version": result.eligibility.trace.rule_version,
        },
        "average_grade": _average_grade_payload(result),
        "admission_result": _admission_result_payload(result),
        "evidence": [
            {
                "rule_kind": item.rule_kind,
                "rule_version": item.rule_version,
                "source_document_id": item.source_document_id,
                "document_type": item.document_type,
                "document_status": item.document_status,
                "page_number": item.page_number,
                "locator": item.locator,
            }
            for item in result.evidence
        ],
        "warnings": list(result.warnings),
    }


def _target_payload(target: Any) -> dict[str, Any]:
    return {
        "academic_year": target.academic_year,
        "institution_name": target.institution_name,
        "campus_name": target.campus_name,
        "program_name": target.program_name,
        "admission_round_name": target.admission_round_name,
        "admission_track_name": target.admission_track_name,
    }


def _average_grade_payload(result: ConsultationResult) -> dict[str, Any] | None:
    grade = result.reflected_grade
    if grade is None:
        return None
    return {
        "unrounded_average_grade": _decimal(grade.unrounded_average_grade),
        "final_average_grade": _decimal(grade.final_average_grade),
        "display_average_grade": _decimal(grade.display_average_grade),
        "grade_scale": grade.grade_scale,
        "rule_version": grade.trace.rule_version,
        "weighting_mode": grade.trace.weighting_mode,
        "rounding_mode": grade.trace.rounding_mode,
        "rounding_scale": grade.trace.rounding_scale,
    }


def _admission_result_payload(result: ConsultationResult) -> dict[str, Any]:
    comparison = result.admission_result
    published = comparison.result
    if published is None:
        return {"status": comparison.status.value}
    average_grade = _decimal(comparison.display_average_grade)
    return {
        "status": comparison.status.value,
        "academic_year": published.key.academic_year,
        "competition_rate": _decimal(published.competition_rate),
        "average_grade": average_grade,
        "score_basis": published.score_basis,
        "publication_version": published.publication_version,
    }


def _validate_payload_keys(data: dict[str, Any]) -> None:
    if frozenset(data) != TOP_LEVEL_KEYS or data.get("schema_version") != 2:
        raise ValueError("AI payload 최상위 필드가 고정 schema와 다릅니다.")
    results = data.get("results")
    if not isinstance(results, list) or not results:
        raise ValueError("AI payload results는 비어 있지 않은 배열이어야 합니다.")
    for row in results:
        _require_exact_keys(row, RESULT_KEYS, "results")
        _require_exact_keys(row["target"], TARGET_KEYS, "target")
        if row["eligibility"] is not None:
            _require_exact_keys(row["eligibility"], ELIGIBILITY_KEYS, "eligibility")
        if row["average_grade"] is not None:
            _require_exact_keys(row["average_grade"], AVERAGE_GRADE_KEYS, "average_grade")
        admission = row["admission_result"]
        if not isinstance(admission, dict) or frozenset(admission) not in {
            frozenset({"status"}),
            ADMISSION_RESULT_KEYS,
        }:
            raise ValueError("AI payload admission_result 필드가 고정 schema와 다릅니다.")
        if not isinstance(row["evidence"], list) or not isinstance(row["warnings"], list):
            raise ValueError("AI payload evidence와 warnings는 배열이어야 합니다.")
        for evidence in row["evidence"]:
            _require_exact_keys(evidence, EVIDENCE_KEYS, "evidence")


def _require_exact_keys(value: object, allowed: frozenset[str], field: str) -> None:
    if not isinstance(value, dict) or frozenset(value) != allowed:
        raise ValueError(f"AI payload {field} 필드가 고정 schema와 다릅니다.")


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


__all__ = [
    "ANONYMOUS_PAYLOAD_SCHEMA_VERSION",
    "AnonymousConsultationPayload",
    "build_anonymous_consultation_payload",
    "validated_saved_payload_copy",
    "validated_payload_copy",
]
