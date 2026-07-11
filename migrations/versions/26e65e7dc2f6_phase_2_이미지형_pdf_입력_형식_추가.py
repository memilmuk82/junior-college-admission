"""Phase 2 이미지형 PDF 입력 형식 추가

Revision ID: 26e65e7dc2f6
Revises: 6f34c170ea52
Create Date: 2026-07-11 22:54:35.569670
"""

from collections.abc import Sequence

from alembic import op

revision: str = "26e65e7dc2f6"
down_revision: str | None = "6f34c170ea52"
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
        "'image_png', 'image_jpeg', 'clipboard_image', 'scanned_pdf')",
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
        "source_format IN ('csv', 'pasted_table', 'xlsx', 'text_pdf', "
        "'image_png', 'image_jpeg', 'clipboard_image')",
    )
