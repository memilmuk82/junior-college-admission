"""Phase 15 institutional anonymous application outcomes."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4a7c9e12d5f0"
down_revision: str | None = "2f8a4c6e91d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_documents", sa.Column("admission_round_id", sa.String(length=36), nullable=True)
    )
    op.add_column(
        "source_documents", sa.Column("original_url", sa.String(length=1000), nullable=True)
    )
    op.add_column(
        "source_documents", sa.Column("announced_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "source_documents", sa.Column("original_filename", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "source_documents", sa.Column("storage_path", sa.String(length=500), nullable=True)
    )
    op.add_column(
        "source_documents",
        sa.Column("is_current", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_foreign_key(
        "fk_source_documents_admission_round_id",
        "source_documents",
        "admission_rounds",
        ["admission_round_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_source_documents_admission_round_id"),
        "source_documents",
        ["admission_round_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_documents_is_current"), "source_documents", ["is_current"], unique=False
    )
    op.create_table(
        "data_validation_decisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_document_id", sa.String(length=36), nullable=False),
        sa.Column("entity_type", sa.String(length=30), nullable=False),
        sa.Column("entity_reference", sa.String(length=160), nullable=False),
        sa.Column("field_name", sa.String(length=120), nullable=False),
        sa.Column("current_value", sa.Text(), nullable=True),
        sa.Column("portal_value", sa.Text(), nullable=True),
        sa.Column("document_value", sa.Text(), nullable=True),
        sa.Column("resolution_status", sa.String(length=20), nullable=False),
        sa.Column("resolved_value", sa.Text(), nullable=True),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.Column("reviewed_by_user_account_id", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "entity_type IN ('CATALOG', 'RULE', 'ADMISSION_RESULT')",
            name="ck_data_validation_decisions_entity_type_valid",
        ),
        sa.CheckConstraint(
            "resolution_status IN ('PENDING', 'CONFIRMED', 'REJECTED')",
            name="ck_data_validation_decisions_resolution_status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_account_id"], ["user_accounts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"], ["source_documents.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_data_validation_decisions_source_document_id"),
        "data_validation_decisions",
        ["source_document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_data_validation_decisions_entity_reference"),
        "data_validation_decisions",
        ["entity_reference"],
        unique=False,
    )
    op.create_index(
        op.f("ix_data_validation_decisions_resolution_status"),
        "data_validation_decisions",
        ["resolution_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_data_validation_decisions_reviewed_by_user_account_id"),
        "data_validation_decisions",
        ["reviewed_by_user_account_id"],
        unique=False,
    )
    op.create_table(
        "institution_application_outcomes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("managed_by_user_account_id", sa.String(length=36), nullable=False),
        sa.Column("anonymous_student_code", sa.String(length=40), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("admission_track_id", sa.String(length=36), nullable=False),
        sa.Column("reflected_grade", sa.Numeric(precision=4, scale=2), nullable=True),
        sa.Column("outcome_status", sa.String(length=30), nullable=False),
        sa.Column("initial_waitlist_number", sa.Integer(), nullable=True),
        sa.Column("final_waitlist_number", sa.Integer(), nullable=True),
        sa.Column("source_status", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "academic_year BETWEEN 2000 AND 2100",
            name="ck_institution_application_outcomes_academic_year_valid",
        ),
        sa.CheckConstraint(
            "outcome_status IN ('INITIAL_ACCEPTED', 'WAITLIST_ACCEPTED', 'REJECTED', 'UNKNOWN')",
            name="ck_institution_application_outcomes_outcome_status_valid",
        ),
        sa.CheckConstraint(
            "source_status IN ('STUDENT_REPORTED', 'TEACHER_CONFIRMED', 'OFFICIAL_CONFIRMED', 'UNCONFIRMED')",
            name="ck_institution_application_outcomes_source_status_valid",
        ),
        sa.CheckConstraint(
            "reflected_grade IS NULL OR reflected_grade BETWEEN 1 AND 9",
            name="ck_institution_application_outcomes_reflected_grade_valid",
        ),
        sa.CheckConstraint(
            "initial_waitlist_number IS NULL OR initial_waitlist_number > 0",
            name="ck_institution_application_outcomes_initial_waitlist_number_positive",
        ),
        sa.CheckConstraint(
            "final_waitlist_number IS NULL OR final_waitlist_number > 0",
            name="ck_institution_application_outcomes_final_waitlist_number_positive",
        ),
        sa.ForeignKeyConstraint(
            ["admission_track_id"], ["admission_tracks.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["managed_by_user_account_id"], ["user_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "managed_by_user_account_id",
            "anonymous_student_code",
            "academic_year",
            "admission_track_id",
            name="uq_institution_outcome_teacher_student_track",
        ),
    )
    op.create_index(
        op.f("ix_institution_application_outcomes_managed_by_user_account_id"),
        "institution_application_outcomes",
        ["managed_by_user_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_institution_application_outcomes_anonymous_student_code"),
        "institution_application_outcomes",
        ["anonymous_student_code"],
        unique=False,
    )
    op.create_index(
        op.f("ix_institution_application_outcomes_academic_year"),
        "institution_application_outcomes",
        ["academic_year"],
        unique=False,
    )
    op.create_index(
        op.f("ix_institution_application_outcomes_admission_track_id"),
        "institution_application_outcomes",
        ["admission_track_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_institution_application_outcomes_admission_track_id"),
        table_name="institution_application_outcomes",
    )
    op.drop_index(
        op.f("ix_institution_application_outcomes_academic_year"),
        table_name="institution_application_outcomes",
    )
    op.drop_index(
        op.f("ix_institution_application_outcomes_anonymous_student_code"),
        table_name="institution_application_outcomes",
    )
    op.drop_index(
        op.f("ix_institution_application_outcomes_managed_by_user_account_id"),
        table_name="institution_application_outcomes",
    )
    op.drop_table("institution_application_outcomes")
    op.drop_index(
        op.f("ix_data_validation_decisions_reviewed_by_user_account_id"),
        table_name="data_validation_decisions",
    )
    op.drop_index(
        op.f("ix_data_validation_decisions_resolution_status"),
        table_name="data_validation_decisions",
    )
    op.drop_index(
        op.f("ix_data_validation_decisions_entity_reference"),
        table_name="data_validation_decisions",
    )
    op.drop_index(
        op.f("ix_data_validation_decisions_source_document_id"),
        table_name="data_validation_decisions",
    )
    op.drop_table("data_validation_decisions")
    op.drop_index(op.f("ix_source_documents_is_current"), table_name="source_documents")
    op.drop_index(op.f("ix_source_documents_admission_round_id"), table_name="source_documents")
    op.drop_constraint(
        "fk_source_documents_admission_round_id", "source_documents", type_="foreignkey"
    )
    op.drop_column("source_documents", "is_current")
    op.drop_column("source_documents", "storage_path")
    op.drop_column("source_documents", "original_filename")
    op.drop_column("source_documents", "announced_at")
    op.drop_column("source_documents", "original_url")
    op.drop_column("source_documents", "admission_round_id")
