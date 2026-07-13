"""Phase 7 DRAFT 편집 감사 동작

Revision ID: c42b718da936
Revises: b91f624ac807
Create Date: 2026-07-13 14:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c42b718da936"
down_revision: str | None = "b91f624ac807"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_rule_audit_events_action_valid"),
        "rule_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_rule_audit_events_action_valid"),
        "rule_audit_events",
        "action IN ('DRAFT_CREATED', 'DRAFT_CLONED', 'HUMAN_APPROVED', "
        "'PUBLISHED', 'SUPERSEDED', 'REJECTED')",
    )
