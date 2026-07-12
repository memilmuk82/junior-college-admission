"""Phase 4 성적 범위 규칙 단일 버전 보장

Revision ID: 9d4e67a213bc
Revises: 7b21c4ad91ef
Create Date: 2026-07-12 04:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d4e67a213bc"
down_revision: str | None = "7b21c4ad91ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_grade_source_scope_rules_one_published_per_track",
        "grade_source_scope_rules",
        ["admission_track_id"],
        unique=True,
        postgresql_where=sa.text("lifecycle_status = 'PUBLISHED'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_grade_source_scope_rules_one_published_per_track",
        table_name="grade_source_scope_rules",
    )
