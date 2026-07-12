"""Phase 4 성적 계산 규칙 단일 버전 보장

Revision ID: c8a4b2f719d0
Revises: 9d4e67a213bc
Create Date: 2026-07-12 10:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8a4b2f719d0"
down_revision: str | None = "9d4e67a213bc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_score_rules_one_published_per_track",
        "score_rules",
        ["admission_track_id"],
        unique=True,
        postgresql_where=sa.text("lifecycle_status = 'PUBLISHED'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_score_rules_one_published_per_track",
        table_name="score_rules",
    )
