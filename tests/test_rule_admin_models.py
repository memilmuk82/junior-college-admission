from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models import (
    AdmissionRound,
    AdmissionTrack,
    Campus,
    Institution,
    Program,
    RuleAuditEvent,
    RuleVersionLineage,
    ScoreRule,
    SourceCitation,
    SourceDocument,
)
from app.services.rule_admin import (
    HumanApproval,
    RuleAdministrationError,
    clone_published_rule_as_draft,
    human_approve_tested_rule,
    publish_human_approved_rule,
)


@pytest.fixture
def session(postgres_engine: Engine) -> Iterator[Session]:
    connection = postgres_engine.connect()
    transaction = connection.begin()
    database_session = Session(bind=connection)
    try:
        yield database_session
    finally:
        database_session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _published_score_rule(session: Session) -> ScoreRule:
    institution = Institution(name="합성 규칙 대학", institution_type="JUNIOR_COLLEGE")
    session.add(institution)
    session.flush()
    campus = Campus(institution_id=institution.id, name="합성 캠퍼스")
    session.add(campus)
    session.flush()
    program = Program(campus_id=campus.id, name="합성 학과")
    admission_round = AdmissionRound(
        institution_id=institution.id, academic_year=2027, code="EARLY_1", name="수시 1차"
    )
    session.add_all([program, admission_round])
    session.flush()
    track = AdmissionTrack(
        admission_round_id=admission_round.id,
        program_id=program.id,
        code="GENERAL",
        name="일반전형",
    )
    document = SourceDocument(
        academic_year=2027,
        institution_id=institution.id,
        campus_id=campus.id,
        document_type="FINAL_GUIDE",
        document_status="HUMAN_APPROVED",
        file_hash="d" * 64,
        page_count=1,
        detected_years=[2027],
        year_consistency_status="CONSISTENT",
        verification_status="HUMAN_APPROVED",
    )
    session.add_all([track, document])
    session.flush()
    citation = SourceCitation(source_document_id=document.id, page_number=1, locator="합성 표")
    session.add(citation)
    session.flush()
    rule = ScoreRule(
        admission_track_id=track.id,
        version="official-v1",
        lifecycle_status="PUBLISHED",
        rule_payload={"schema_version": 1, "maximum_score": "100"},
        source_citation_id=citation.id,
        independent_verified=True,
        golden_test_ref="tests/synthetic::v1",
        human_approved_at=datetime(2026, 7, 13, tzinfo=UTC),
        admission_year=2027,
        university_code="SYNTHETIC_U",
        university_name="합성 규칙 대학",
        campus_code="MAIN",
        admission_round="EARLY_1",
        admission_track_code="GENERAL",
        admission_track_name="일반전형",
        evidence_document_ref=document.id,
        evidence_page=1,
        evidence_location="합성 표",
        source_status="FINAL_GUIDE",
        change_reason="합성 최초 규칙",
    )
    session.add(rule)
    session.flush()
    return rule


def test_published_rule_is_cloned_approved_and_replaced_with_audit(session: Session) -> None:
    source = _published_score_rule(session)
    occurred_at = datetime(2026, 7, 13, 2, 0, tzinfo=UTC)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="official-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 변경 검수",
        occurred_at=occurred_at,
    )
    assert source.lifecycle_status == "PUBLISHED"
    assert draft.lifecycle_status == "DRAFT"
    assert draft.rule_payload == source.rule_payload
    assert draft.university_code == source.university_code
    assert draft.evidence_document_ref == source.evidence_document_ref
    assert draft.independent_verified is False
    lineage = session.scalar(
        select(RuleVersionLineage).where(RuleVersionLineage.rule_id == draft.id)
    )
    assert lineage is not None and lineage.supersedes_rule_id == source.id

    draft.lifecycle_status = "TESTED"
    draft.independent_verified = True
    draft.golden_test_ref = "tests/synthetic::v2"
    approved = human_approve_tested_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=draft.id,
        approval=HumanApproval("synthetic-admin", occurred_at, "HUMAN_APPROVED"),
    )
    publish_human_approved_rule(
        session,
        rule_type="SCORE_RULE",
        rule_id=approved.id,
        actor_ref="synthetic-admin",
        occurred_at=occurred_at,
    )
    assert approved.lifecycle_status == "PUBLISHED"
    assert source.lifecycle_status == "SUPERSEDED"
    actions = tuple(
        session.scalars(select(RuleAuditEvent.action).order_by(RuleAuditEvent.created_at))
    )
    assert actions == ("DRAFT_CLONED", "HUMAN_APPROVED", "SUPERSEDED", "PUBLISHED")


def test_human_approval_requires_explicit_confirmation(session: Session) -> None:
    source = _published_score_rule(session)
    draft = clone_published_rule_as_draft(
        session,
        rule_type="SCORE_RULE",
        source_rule_id=source.id,
        new_version="official-v2",
        actor_ref="synthetic-admin",
        change_reason="합성 변경",
        occurred_at=datetime(2026, 7, 13, tzinfo=UTC),
    )
    draft.lifecycle_status = "TESTED"
    draft.independent_verified = True
    draft.golden_test_ref = "tests/synthetic::v2"
    with pytest.raises(RuleAdministrationError):
        human_approve_tested_rule(
            session,
            rule_type="SCORE_RULE",
            rule_id=draft.id,
            approval=HumanApproval(
                "synthetic-admin", datetime(2026, 7, 13, tzinfo=UTC), "AI_APPROVED"
            ),
        )
