from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.models import RuleAuditEvent, RuleVersionLineage, ScoreRule
from app.services.score_rule_csv_drafts import (
    load_managed_score_rules,
    persist_score_rule_drafts,
)
from app.services.score_rule_csv_preview import (
    build_score_rule_csv_preview,
    prepare_selected_score_rule_drafts,
)
from app.services.score_rule_schema import parse_score_rule_csv, write_score_rule_csv
from tests.test_score_rule_schema import _csv_bytes, _valid_row


def _managed():  # type: ignore[no-untyped-def]
    parsed = parse_score_rule_csv(_csv_bytes([_valid_row()]))
    assert parsed.issues == ()
    return parsed.rows[0]


def test_selected_csv_rows_create_versioned_unpublished_drafts(
    postgres_engine: Engine,
) -> None:
    initial = _managed()
    with Session(postgres_engine) as session:
        preview = build_score_rule_csv_preview(write_score_rule_csv((initial,)), ())
        candidates = prepare_selected_score_rule_drafts(preview, (initial.identity.key,))
        first = persist_score_rule_drafts(
            session,
            candidates=candidates,
            actor_ref="synthetic-admin",
            occurred_at=datetime.now(UTC),
        )[0]
        session.commit()
        first_id = first.id

    with Session(postgres_engine) as session:
        current = load_managed_score_rules(session)
        changed = replace(
            initial,
            rule_version="synthetic-v2",
            definition=replace(initial.definition, maximum_score=Decimal("900")),
            change_reason="합성 배점 변경",
        )
        preview = build_score_rule_csv_preview(write_score_rule_csv((changed,)), current)
        assert preview.items[0].classification == "CHANGED"
        candidates = prepare_selected_score_rule_drafts(preview, (changed.identity.key,))
        second = persist_score_rule_drafts(
            session,
            candidates=candidates,
            actor_ref="synthetic-admin",
            occurred_at=datetime.now(UTC),
        )[0]
        session.commit()
        second_id = second.id

    with Session(postgres_engine) as session:
        first_loaded = session.get(ScoreRule, first_id)
        second_loaded = session.get(ScoreRule, second_id)
        assert first_loaded is not None and second_loaded is not None
        assert first_loaded.lifecycle_status == second_loaded.lifecycle_status == "DRAFT"
        assert (
            first_loaded.rule_payload["maximum_score"]
            != second_loaded.rule_payload["maximum_score"]
        )
        lineage = session.scalar(
            select(RuleVersionLineage).where(RuleVersionLineage.rule_id == second_id)
        )
        assert lineage is not None
        assert lineage.supersedes_rule_id == first_id
        actions = tuple(
            session.scalars(
                select(RuleAuditEvent.action)
                .where(RuleAuditEvent.rule_id.in_((first_id, second_id)))
                .order_by(RuleAuditEvent.created_at)
            )
        )
        assert actions == ("DRAFT_CREATED", "DRAFT_CREATED")
        session.execute(
            delete(RuleAuditEvent).where(RuleAuditEvent.rule_id.in_((first_id, second_id)))
        )
        session.execute(delete(RuleVersionLineage).where(RuleVersionLineage.rule_id == second_id))
        session.execute(delete(ScoreRule).where(ScoreRule.id.in_((first_id, second_id))))
        session.commit()
