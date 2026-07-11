"""Phase 2 이미지 OCR 입력 형식 추가

Revision ID: 6f34c170ea52
Revises: 0df6e174521e
Create Date: 2026-07-11 16:04:41.203287
"""

from collections.abc import Sequence

from alembic import op

revision: str = "6f34c170ea52"
down_revision: str | None = "0df6e174521e"
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
        "source_format IN ('csv', 'pasted_table', 'xlsx', 'text_pdf', "
        "'image_png', 'image_jpeg', 'clipboard_image')",
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
        "source_format IN ('csv', 'pasted_table', 'xlsx', 'text_pdf')",
    )
