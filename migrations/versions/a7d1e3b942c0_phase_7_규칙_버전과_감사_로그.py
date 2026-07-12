"""Phase 7 규칙 버전과 감사 로그

Revision ID: a7d1e3b942c0
Revises: f4c2a91d6e73
Create Date: 2026-07-13 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d1e3b942c0"
down_revision: str | None = "f4c2a91d6e73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rule_version_lineages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rule_type", sa.String(length=80), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("supersedes_rule_id", sa.String(length=36), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "rule_id != supersedes_rule_id",
            name=op.f("ck_rule_version_lineages_not_self_superseding"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_version_lineages")),
        sa.UniqueConstraint(
            "rule_type", "rule_id", name=op.f("uq_rule_version_lineages_rule_type")
        ),
    )
    for column in ("rule_id", "rule_type", "supersedes_rule_id"):
        op.create_index(
            op.f(f"ix_rule_version_lineages_{column}"),
            "rule_version_lineages",
            [column],
        )
    op.create_table(
        "rule_audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rule_type", sa.String(length=80), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("actor_ref", sa.String(length=120), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("before_payload_digest", sa.String(length=64), nullable=True),
        sa.Column("after_payload_digest", sa.String(length=64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('DRAFT_CLONED', 'HUMAN_APPROVED', 'PUBLISHED', 'SUPERSEDED', 'REJECTED')",
            name=op.f("ck_rule_audit_events_action_valid"),
        ),
        sa.CheckConstraint(
            "char_length(actor_ref) > 0", name=op.f("ck_rule_audit_events_actor_present")
        ),
        sa.CheckConstraint(
            "before_payload_digest IS NULL OR char_length(before_payload_digest) = 64",
            name=op.f("ck_rule_audit_events_before_digest_valid"),
        ),
        sa.CheckConstraint(
            "after_payload_digest IS NULL OR char_length(after_payload_digest) = 64",
            name=op.f("ck_rule_audit_events_after_digest_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_audit_events")),
    )
    for column in ("action", "rule_id", "rule_type"):
        op.create_index(
            op.f(f"ix_rule_audit_events_{column}"),
            "rule_audit_events",
            [column],
        )


def downgrade() -> None:
    for column in ("rule_type", "rule_id", "action"):
        op.drop_index(op.f(f"ix_rule_audit_events_{column}"), table_name="rule_audit_events")
    op.drop_table("rule_audit_events")
    for column in ("supersedes_rule_id", "rule_type", "rule_id"):
        op.drop_index(
            op.f(f"ix_rule_version_lineages_{column}"), table_name="rule_version_lineages"
        )
    op.drop_table("rule_version_lineages")
