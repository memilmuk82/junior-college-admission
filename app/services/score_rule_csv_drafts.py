from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import RuleVersionLineage, ScoreRule, SourceCitation
from app.services.rule_admin import record_rule_audit
from app.services.score_rule_csv_preview import (
    RuleBusinessKey,
    ScoreRuleDraftCandidate,
)
from app.services.score_rule_schema import (
    ManagedScoreRule,
    RuleIdentity,
    score_rule_definition_from_payload,
    score_rule_to_payload,
)


class ScoreRuleDraftPersistenceError(ValueError):
    pass


def load_managed_score_rules(session: Session) -> tuple[ManagedScoreRule, ...]:
    rows = session.scalars(
        select(ScoreRule)
        .where(ScoreRule.admission_year.is_not(None))
        .where(ScoreRule.lifecycle_status != "SUPERSEDED")
        .order_by(ScoreRule.created_at.desc())
    )
    return tuple(_managed_rule(row) for row in rows)


def persist_score_rule_drafts(
    session: Session,
    *,
    candidates: tuple[ScoreRuleDraftCandidate, ...],
    actor_ref: str,
    occurred_at: datetime,
) -> tuple[ScoreRule, ...]:
    if not candidates:
        raise ScoreRuleDraftPersistenceError("저장할 DRAFT 후보가 없습니다.")
    keys = tuple(candidate.rule.identity.key for candidate in candidates)
    if len(set(keys)) != len(keys):
        raise ScoreRuleDraftPersistenceError("중복 업무키는 한 번에 저장할 수 없습니다.")
    if not actor_ref.strip() or occurred_at.tzinfo is None:
        raise ScoreRuleDraftPersistenceError(
            "관리자 식별자와 timezone 포함 저장 시각이 필요합니다."
        )

    prepared: list[tuple[ScoreRuleDraftCandidate, ScoreRule | None, str | None]] = []
    for candidate in candidates:
        if candidate.lifecycle_status != "DRAFT" or candidate.auto_publish:
            raise ScoreRuleDraftPersistenceError("검증된 비게시 DRAFT 후보만 저장할 수 있습니다.")
        rule = candidate.rule
        same_version = session.scalar(
            _business_key_query(rule.identity.key).where(ScoreRule.version == rule.rule_version)
        )
        if same_version is not None:
            raise ScoreRuleDraftPersistenceError(
                "동일 업무키와 버전의 규칙이 이미 존재하여 덮어쓸 수 없습니다."
            )
        source = None
        if candidate.supersedes_rule_version is not None:
            sources = tuple(
                session.scalars(
                    _business_key_query(rule.identity.key).where(
                        ScoreRule.version == candidate.supersedes_rule_version
                    )
                )
            )
            if len(sources) != 1:
                raise ScoreRuleDraftPersistenceError(
                    "변경 대상의 이전 규칙 버전을 하나로 식별할 수 없습니다."
                )
            source = sources[0]
        citation_id = _resolve_citation_id(session, rule)
        prepared.append((candidate, source, citation_id))

    drafts: list[ScoreRule] = []
    for candidate, source, citation_id in prepared:
        managed = candidate.rule
        draft = ScoreRule(
            admission_track_id=None if source is None else source.admission_track_id,
            version=managed.rule_version,
            lifecycle_status="DRAFT",
            rule_payload=score_rule_to_payload(managed),
            source_citation_id=citation_id,
            independent_verified=False,
            golden_test_ref=None,
            human_approved_at=None,
            admission_year=managed.identity.admission_year,
            university_code=managed.identity.university_code,
            university_name=managed.university_name,
            campus_code=managed.identity.campus_code,
            admission_round=managed.identity.admission_round,
            admission_track_code=managed.identity.admission_track_code,
            admission_track_name=managed.admission_track_name,
            evidence_document_ref=managed.evidence_document_id,
            evidence_page=managed.evidence_page,
            evidence_location=managed.evidence_location,
            source_status=managed.source_status,
            change_reason=managed.change_reason,
            administrator_note=managed.administrator_note,
        )
        session.add(draft)
        session.flush()
        if source is not None:
            session.add(
                RuleVersionLineage(
                    rule_type="SCORE_RULE",
                    rule_id=draft.id,
                    supersedes_rule_id=source.id,
                    change_reason=managed.change_reason,
                )
            )
        record_rule_audit(
            session,
            rule_type="SCORE_RULE",
            rule=draft,
            action="DRAFT_CREATED",
            actor_ref=actor_ref,
            occurred_at=occurred_at,
            before_payload=None if source is None else source.rule_payload,
            after_payload=draft.rule_payload,
            details={
                "source": "SCORE_RULE_CSV",
                "supersedes_rule_id": None if source is None else source.id,
                "auto_publish": False,
            },
        )
        drafts.append(draft)
    session.flush()
    return tuple(drafts)


def _business_key_query(key: RuleBusinessKey):  # type: ignore[no-untyped-def]
    year, university, campus, admission_round, track = key
    return select(ScoreRule).where(
        ScoreRule.admission_year == year,
        ScoreRule.university_code == university,
        ScoreRule.campus_code == campus,
        ScoreRule.admission_round == admission_round,
        ScoreRule.admission_track_code == track,
    )


def _managed_rule(row: ScoreRule) -> ManagedScoreRule:
    required = (
        row.admission_year,
        row.university_code,
        row.university_name,
        row.campus_code,
        row.admission_round,
        row.admission_track_code,
        row.admission_track_name,
        row.source_status,
        row.change_reason,
    )
    if any(value is None for value in required):
        raise ScoreRuleDraftPersistenceError(
            "CSV 관리 규칙의 업무키 또는 관리 메타데이터가 불완전합니다."
        )
    assert row.admission_year is not None
    assert row.university_code is not None
    assert row.university_name is not None
    assert row.campus_code is not None
    assert row.admission_round is not None
    assert row.admission_track_code is not None
    assert row.admission_track_name is not None
    assert row.source_status is not None
    assert row.change_reason is not None
    return ManagedScoreRule(
        identity=RuleIdentity(
            admission_year=int(row.admission_year),
            university_code=str(row.university_code),
            campus_code=str(row.campus_code),
            admission_round=str(row.admission_round),
            admission_track_code=str(row.admission_track_code),
        ),
        university_name=str(row.university_name),
        admission_track_name=str(row.admission_track_name),
        rule_version=row.version,
        definition=score_rule_definition_from_payload(row.rule_payload),
        evidence_document_id=row.evidence_document_ref,
        evidence_page=row.evidence_page,
        evidence_location=row.evidence_location,
        evidence_level=str(row.rule_payload["evidence_level"]),
        source_status=str(row.source_status),
        change_reason=str(row.change_reason),
        administrator_note=row.administrator_note,
    )


def _resolve_citation_id(session: Session, rule: ManagedScoreRule) -> str | None:
    if not rule.evidence_document_id or rule.evidence_page is None:
        return None
    matches = tuple(
        session.scalars(
            select(SourceCitation).where(
                SourceCitation.source_document_id == rule.evidence_document_id,
                SourceCitation.page_number == rule.evidence_page,
                SourceCitation.locator == rule.evidence_location,
            )
        )
    )
    return matches[0].id if len(matches) == 1 else None


__all__ = [
    "ScoreRuleDraftPersistenceError",
    "load_managed_score_rules",
    "persist_score_rule_drafts",
]
