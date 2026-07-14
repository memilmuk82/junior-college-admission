"""Phase 10 규칙 검수 감사 동작

Revision ID: f76a91c3d2e8
Revises: e51f0b24c8aa
Create Date: 2026-07-15 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f76a91c3d2e8"
down_revision: str | None = "e51f0b24c8aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rule_reviews",
        sa.Column("payload_digest", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_rule_reviews_payload_digest_valid"),
        "rule_reviews",
        "payload_digest IS NULL OR char_length(payload_digest) = 64",
    )
    op.add_column(
        "rule_reviews",
        sa.Column("contract_digest", sa.String(length=64), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_rule_reviews_contract_digest_valid"),
        "rule_reviews",
        "contract_digest IS NULL OR char_length(contract_digest) = 64",
    )
    op.add_column(
        "rule_reviews",
        sa.Column("contract_schema_version", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_rule_reviews_contract_schema_version_valid"),
        "rule_reviews",
        "contract_schema_version IS NULL OR contract_schema_version > 0",
    )
    op.drop_constraint(
        op.f("ck_rule_audit_events_action_valid"),
        "rule_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_rule_audit_events_action_valid"),
        "rule_audit_events",
        "action IN ('DRAFT_CREATED', 'DRAFT_CLONED', 'DRAFT_UPDATED', 'EXTRACTED', "
        "'VERIFIED', 'TESTED', 'HUMAN_APPROVED', 'PUBLISHED', 'SUPERSEDED', "
        "'REJECTED')",
    )


def downgrade() -> None:
    op.execute("LOCK TABLE rule_reviews, rule_audit_events IN ACCESS EXCLUSIVE MODE")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM rule_audit_events "
        "WHERE action IN ('EXTRACTED', 'VERIFIED', 'TESTED')) "
        "OR EXISTS (SELECT 1 FROM rule_reviews "
        "WHERE payload_digest IS NOT NULL OR contract_digest IS NOT NULL "
        "OR contract_schema_version IS NOT NULL) THEN "
        "RAISE EXCEPTION '규칙 검수 계약 데이터 또는 감사 이벤트를 보존한 채 "
        "이전 제약으로 내릴 수 없습니다.'; "
        "END IF; END $$"
    )
    op.drop_constraint(
        op.f("ck_rule_audit_events_action_valid"),
        "rule_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_rule_audit_events_action_valid"),
        "rule_audit_events",
        "action IN ('DRAFT_CREATED', 'DRAFT_CLONED', 'DRAFT_UPDATED', "
        "'HUMAN_APPROVED', 'PUBLISHED', 'SUPERSEDED', 'REJECTED')",
    )
    op.drop_constraint(
        op.f("ck_rule_reviews_contract_schema_version_valid"),
        "rule_reviews",
        type_="check",
    )
    op.drop_column("rule_reviews", "contract_schema_version")
    op.drop_constraint(
        op.f("ck_rule_reviews_contract_digest_valid"),
        "rule_reviews",
        type_="check",
    )
    op.drop_column("rule_reviews", "contract_digest")
    op.drop_constraint(
        op.f("ck_rule_reviews_payload_digest_valid"),
        "rule_reviews",
        type_="check",
    )
    op.drop_column("rule_reviews", "payload_digest")
