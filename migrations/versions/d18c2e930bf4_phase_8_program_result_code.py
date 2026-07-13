"""Phase 8 학과 입시결과 코드

Revision ID: d18c2e930bf4
Revises: c42b718da936
Create Date: 2026-07-13 17:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d18c2e930bf4"
down_revision: str | None = "c42b718da936"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("programs", sa.Column("code", sa.String(length=120), nullable=True))
    op.create_unique_constraint(
        op.f("uq_programs_campus_id_code"),
        "programs",
        ["campus_id", "code"],
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_programs_campus_id_code"), "programs", type_="unique")
    op.drop_column("programs", "code")
