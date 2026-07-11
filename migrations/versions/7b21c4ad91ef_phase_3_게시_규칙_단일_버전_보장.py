"""Phase 3 게시 규칙 단일 버전 보장

Revision ID: 7b21c4ad91ef
Revises: 26e65e7dc2f6
Create Date: 2026-07-12 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7b21c4ad91ef"
down_revision: str | None = "26e65e7dc2f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table_name in (
        "admission_eligibility_rules",
        "multiple_application_rules",
        "disqualification_rules",
    ):
        op.create_index(
            f"uq_{table_name}_one_published_per_track",
            table_name,
            ["admission_track_id"],
            unique=True,
            postgresql_where=sa.text("lifecycle_status = 'PUBLISHED'"),
        )


def downgrade() -> None:
    for table_name in (
        "disqualification_rules",
        "multiple_application_rules",
        "admission_eligibility_rules",
    ):
        op.drop_index(
            f"uq_{table_name}_one_published_per_track",
            table_name=table_name,
        )
