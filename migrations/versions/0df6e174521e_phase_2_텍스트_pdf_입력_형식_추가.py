"""Phase 2 텍스트 PDF 입력 형식 추가

Revision ID: 0df6e174521e
Revises: 341a80ddba84
Create Date: 2026-07-11 15:11:07.980574
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0df6e174521e"
down_revision: str | None = "341a80ddba84"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_import_batches_source_format_valid"),
        "import_batches",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_import_batches_source_format_valid"),
        "import_batches",
        "source_format IN ('csv', 'pasted_table', 'xlsx', 'text_pdf')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_import_batches_source_format_valid"),
        "import_batches",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_import_batches_source_format_valid"),
        "import_batches",
        "source_format IN ('csv', 'pasted_table', 'xlsx')",
    )
