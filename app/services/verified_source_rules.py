from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserAccount, VerifiedSourceRuleConfirmation
from app.services.eligibility import validate_eligibility_rule_payload
from app.services.score_inputs import validate_grade_source_scope_payload
from app.services.score_rule_schema import ZScoreTableRow, validate_score_rule_payload

DEFAULT_VERIFIED_SOURCE_RULE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "seed" / "phase14_verified_source_rules.json"
)


class VerifiedSourceRuleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedSourceEvidence:
    document_name: str
    academic_year: int
    page_number: int
    locator: str
    source_status: str


@dataclass(frozen=True, slots=True)
class VerifiedSourceRule:
    academic_year: int
    institution_code: str
    campus_code: str
    admission_round_code: str
    admission_track_code: str
    rule_id: str
    version: str
    execution_status: str
    eligibility_payload: Mapping[str, object]
    grade_source_payload: dict[str, object]
    score_rule_payload: Mapping[str, object]
    evidence: Mapping[str, VerifiedSourceEvidence]
    z_score_table_version: str | None = None
    z_score_table_rows: tuple[ZScoreTableRow, ...] = ()


def load_verified_source_rules(
    path: Path = DEFAULT_VERIFIED_SOURCE_RULE_PATH,
) -> tuple[VerifiedSourceRule, ...]:
    if not path.is_file():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1 or not isinstance(payload.get("rules"), list):
            raise VerifiedSourceRuleError("VERIFIED_SOURCE 규칙 파일 형식이 유효하지 않습니다.")
        rules = tuple(_parse_rule(item) for item in payload["rules"])
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError) as error:
        raise VerifiedSourceRuleError("VERIFIED_SOURCE 규칙 파일을 읽을 수 없습니다.") from error
    keys = [
        (
            rule.academic_year,
            rule.institution_code,
            rule.campus_code,
            rule.admission_round_code,
            rule.admission_track_code,
        )
        for rule in rules
    ]
    if len(keys) != len(set(keys)):
        raise VerifiedSourceRuleError("VERIFIED_SOURCE 규칙 업무키가 중복되었습니다.")
    return rules


def find_verified_source_rule(
    *,
    academic_year: int,
    institution_code: str,
    campus_code: str,
    admission_round_code: str,
    admission_track_code: str,
    path: Path = DEFAULT_VERIFIED_SOURCE_RULE_PATH,
) -> VerifiedSourceRule | None:
    key = (
        academic_year,
        institution_code,
        campus_code,
        admission_round_code,
        admission_track_code,
    )
    return next(
        (
            rule
            for rule in load_verified_source_rules(path)
            if (
                rule.academic_year,
                rule.institution_code,
                rule.campus_code,
                rule.admission_round_code,
                rule.admission_track_code,
            )
            == key
        ),
        None,
    )


def verified_source_rule_digest(rule: VerifiedSourceRule) -> str:
    canonical = json.dumps(
        asdict(rule), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def confirmed_verified_source_rule(
    session: Session, rule: VerifiedSourceRule
) -> VerifiedSourceRuleConfirmation | None:
    confirmation = session.scalar(
        select(VerifiedSourceRuleConfirmation).where(
            VerifiedSourceRuleConfirmation.rule_id == rule.rule_id,
            VerifiedSourceRuleConfirmation.rule_version == rule.version,
        )
    )
    if confirmation is None or confirmation.source_digest != verified_source_rule_digest(rule):
        return None
    return confirmation


def confirm_verified_source_rule(
    session: Session, *, rule: VerifiedSourceRule, actor: UserAccount
) -> VerifiedSourceRuleConfirmation:
    if actor.role != "ADMIN" or actor.status != "ACTIVE":
        raise VerifiedSourceRuleError("활성 관리자만 공식 출처 규칙을 최종 확인할 수 있습니다.")
    if rule.execution_status != "VERIFIED_SOURCE":
        raise VerifiedSourceRuleError("검수 대기 규칙은 최종 확인할 수 없습니다.")
    confirmation = session.scalar(
        select(VerifiedSourceRuleConfirmation)
        .where(
            VerifiedSourceRuleConfirmation.rule_id == rule.rule_id,
            VerifiedSourceRuleConfirmation.rule_version == rule.version,
        )
        .with_for_update()
    )
    digest = verified_source_rule_digest(rule)
    if confirmation is None:
        confirmation = VerifiedSourceRuleConfirmation(
            rule_id=rule.rule_id,
            rule_version=rule.version,
            source_digest=digest,
            confirmed_by_user_account_id=actor.id,
            confirmed_at=datetime.now(UTC),
        )
        session.add(confirmation)
    else:
        confirmation.source_digest = digest
        confirmation.confirmed_by_user_account_id = actor.id
        confirmation.confirmed_at = datetime.now(UTC)
    session.flush()
    return confirmation


def _parse_rule(raw: Any) -> VerifiedSourceRule:
    if not isinstance(raw, dict):
        raise VerifiedSourceRuleError("VERIFIED_SOURCE 규칙 행이 객체가 아닙니다.")
    evidence_raw = raw["evidence"]
    if not isinstance(evidence_raw, dict):
        raise VerifiedSourceRuleError("VERIFIED_SOURCE 근거가 객체가 아닙니다.")
    execution_status = str(raw["execution_status"])
    if execution_status not in {"VERIFIED_SOURCE", "NEEDS_REVIEW"}:
        raise VerifiedSourceRuleError("VERIFIED_SOURCE 실행 상태가 유효하지 않습니다.")
    eligibility_payload = raw["eligibility_payload"]
    grade_source_payload = raw["grade_source_payload"]
    score_rule_payload = raw["score_rule_payload"]
    if not isinstance(eligibility_payload, dict):
        raise VerifiedSourceRuleError("지원자격 규칙 payload가 객체가 아닙니다.")
    if not isinstance(grade_source_payload, dict):
        raise VerifiedSourceRuleError("성적 범위 규칙 payload가 객체가 아닙니다.")
    if not isinstance(score_rule_payload, dict):
        raise VerifiedSourceRuleError("성적 계산 규칙 payload가 객체가 아닙니다.")
    validate_eligibility_rule_payload(eligibility_payload)
    validate_grade_source_scope_payload(grade_source_payload)
    validate_score_rule_payload(score_rule_payload)
    evidence = {
        kind: _parse_evidence(evidence_raw[kind])
        for kind in ("eligibility", "grade_source", "score")
    }
    table_version, table_rows = _parse_z_score_table(raw.get("z_score_table"))
    rule = VerifiedSourceRule(
        academic_year=int(raw["academic_year"]),
        institution_code=str(raw["institution_code"]),
        campus_code=str(raw["campus_code"]),
        admission_round_code=str(raw["admission_round_code"]),
        admission_track_code=str(raw["admission_track_code"]),
        rule_id=str(raw["rule_id"]),
        version=str(raw["version"]),
        execution_status=execution_status,
        eligibility_payload=eligibility_payload,
        grade_source_payload=grade_source_payload,
        score_rule_payload=score_rule_payload,
        evidence=evidence,
        z_score_table_version=table_version,
        z_score_table_rows=table_rows,
    )
    required = (
        rule.institution_code,
        rule.campus_code,
        rule.admission_round_code,
        rule.admission_track_code,
        rule.rule_id,
        rule.version,
        *(item.document_name for item in evidence.values()),
        *(item.locator for item in evidence.values()),
        *(item.source_status for item in evidence.values()),
    )
    if any(not value.strip() for value in required):
        raise VerifiedSourceRuleError("VERIFIED_SOURCE 업무키·버전·근거가 누락되었습니다.")
    if any(
        item.academic_year != rule.academic_year or item.page_number <= 0
        for item in evidence.values()
    ):
        raise VerifiedSourceRuleError("VERIFIED_SOURCE 근거의 학년도·페이지가 다릅니다.")
    return rule


def _parse_z_score_table(raw: object) -> tuple[str | None, tuple[ZScoreTableRow, ...]]:
    if raw is None:
        return None, ()
    if not isinstance(raw, dict) or not isinstance(raw.get("rows"), list):
        raise VerifiedSourceRuleError("VERIFIED_SOURCE Z점수 변환표가 유효하지 않습니다.")
    table_code = str(raw.get("table_code", ""))
    version = str(raw.get("version", ""))
    document_id = str(raw.get("evidence_document_id", ""))
    page = int(raw.get("evidence_page", 0))
    location = str(raw.get("evidence_location", ""))
    source_status = str(raw.get("source_status", ""))
    if not all((table_code, version, document_id, location, source_status)) or page <= 0:
        raise VerifiedSourceRuleError("VERIFIED_SOURCE Z점수 변환표 근거가 누락되었습니다.")

    def optional_decimal(value: object) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

    rows = tuple(
        ZScoreTableRow(
            table_code=table_code,
            z_min=optional_decimal(item.get("z_min")),
            z_min_inclusive=bool(item.get("z_min_inclusive", False)),
            z_max=optional_decimal(item.get("z_max")),
            z_max_inclusive=bool(item.get("z_max_inclusive", False)),
            converted_value=Decimal(str(item["converted_value"])),
            evidence_document_id=document_id,
            evidence_page=page,
            evidence_location=location,
            source_status=source_status,
            change_reason="사용자 제공 2027 모집요강의 공식 등급 환산표",
        )
        for item in raw["rows"]
        if isinstance(item, dict)
    )
    if len(rows) != len(raw["rows"]):
        raise VerifiedSourceRuleError("VERIFIED_SOURCE Z점수 변환표 행이 유효하지 않습니다.")
    return version, rows


def _parse_evidence(raw: object) -> VerifiedSourceEvidence:
    if not isinstance(raw, dict):
        raise VerifiedSourceRuleError("VERIFIED_SOURCE 종류별 근거가 객체가 아닙니다.")
    return VerifiedSourceEvidence(
        document_name=str(raw["document_name"]),
        academic_year=int(raw["academic_year"]),
        page_number=int(raw["page_number"]),
        locator=str(raw["locator"]),
        source_status=str(raw["source_status"]),
    )


__all__ = [
    "VerifiedSourceEvidence",
    "VerifiedSourceRule",
    "VerifiedSourceRuleError",
    "find_verified_source_rule",
    "confirm_verified_source_rule",
    "confirmed_verified_source_rule",
    "load_verified_source_rules",
    "verified_source_rule_digest",
]
