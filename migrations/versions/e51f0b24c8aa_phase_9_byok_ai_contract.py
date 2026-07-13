"""Phase 9 BYOK AI 저장 계약

Revision ID: e51f0b24c8aa
Revises: d18c2e930bf4
Create Date: 2026-07-14 15:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e51f0b24c8aa"
down_revision: str | None = "d18c2e930bf4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_credentials",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor_ref", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("encrypted_api_key", sa.Text(), nullable=False),
        sa.Column("masked_hint", sa.String(length=8), nullable=False),
        sa.Column("encryption_version", sa.String(length=30), nullable=False),
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
            "provider IN ('OPENAI', 'GEMINI', 'ANTHROPIC')",
            name=op.f("ck_ai_provider_credentials_provider_valid"),
        ),
        sa.CheckConstraint(
            "char_length(actor_ref) > 0",
            name=op.f("ck_ai_provider_credentials_actor_present"),
        ),
        sa.CheckConstraint(
            "char_length(encrypted_api_key) > 0",
            name=op.f("ck_ai_provider_credentials_ciphertext_present"),
        ),
        sa.CheckConstraint(
            "char_length(masked_hint) = 8",
            name=op.f("ck_ai_provider_credentials_masked_hint_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_provider_credentials")),
        sa.UniqueConstraint(
            "actor_ref",
            "provider",
            name=op.f("uq_ai_provider_credentials_actor_ref"),
        ),
    )
    op.create_index(
        op.f("ix_ai_provider_credentials_actor_ref"),
        "ai_provider_credentials",
        ["actor_ref"],
    )
    op.create_table(
        "ai_consultation_drafts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor_ref", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("payload_schema_version", sa.Integer(), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("generated_text", sa.Text(), nullable=False),
        sa.Column("check_items", sa.JSON(), nullable=False),
        sa.Column("teacher_text", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("confirmed_by", sa.String(length=120), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
            "provider IN ('OPENAI', 'GEMINI', 'ANTHROPIC')",
            name=op.f("ck_ai_consultation_drafts_provider_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('GENERATED_DRAFT', 'TEACHER_CONFIRMED', 'REJECTED')",
            name=op.f("ck_ai_consultation_drafts_status_valid"),
        ),
        sa.CheckConstraint(
            "char_length(actor_ref) > 0",
            name=op.f("ck_ai_consultation_drafts_actor_present"),
        ),
        sa.CheckConstraint(
            "char_length(payload_digest) = 64",
            name=op.f("ck_ai_consultation_drafts_payload_digest_valid"),
        ),
        sa.CheckConstraint(
            "(status = 'TEACHER_CONFIRMED' AND teacher_text IS NOT NULL "
            "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL) OR "
            "(status IN ('GENERATED_DRAFT', 'REJECTED') AND teacher_text IS NULL "
            "AND confirmed_by IS NULL AND confirmed_at IS NULL)",
            name=op.f("ck_ai_consultation_drafts_confirmed_draft_complete"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_consultation_drafts")),
    )
    op.create_index(
        op.f("ix_ai_consultation_drafts_actor_ref"),
        "ai_consultation_drafts",
        ["actor_ref"],
    )
    op.create_index(
        op.f("ix_ai_consultation_drafts_payload_digest"),
        "ai_consultation_drafts",
        ["payload_digest"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_ai_consultation_drafts_payload_digest"),
        table_name="ai_consultation_drafts",
    )
    op.drop_index(
        op.f("ix_ai_consultation_drafts_actor_ref"),
        table_name="ai_consultation_drafts",
    )
    op.drop_table("ai_consultation_drafts")
    op.drop_index(
        op.f("ix_ai_provider_credentials_actor_ref"),
        table_name="ai_provider_credentials",
    )
    op.drop_table("ai_provider_credentials")
