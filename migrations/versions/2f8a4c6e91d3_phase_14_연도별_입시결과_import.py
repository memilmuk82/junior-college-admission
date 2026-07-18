"""Phase 14 연도별 입시결과 import

Revision ID: 2f8a4c6e91d3
Revises: 6c1a2e9f4b73
"""

import sqlalchemy as sa
from alembic import op

revision: str = "2f8a4c6e91d3"
down_revision: str | None = "6c1a2e9f4b73"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_user_accounts_role_valid"), "user_accounts", type_="check")
    op.create_check_constraint(
        op.f("ck_user_accounts_role_valid"),
        "user_accounts",
        "role IN ('ADMIN', 'ASSISTANT_ADMIN', 'MEMBER', 'STUDENT', 'TEACHER')",
    )
    op.drop_constraint(
        op.f("ck_user_accounts_pending_role_member"),
        "user_accounts",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_user_accounts_pending_role_member"),
        "user_accounts",
        "status NOT IN ('PENDING_APPROVAL', 'REJECTED') "
        "OR role IN ('MEMBER', 'STUDENT', 'TEACHER')",
    )
    op.drop_constraint(
        op.f("ck_user_account_audit_events_before_role_valid"),
        "user_account_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_user_account_audit_events_before_role_valid"),
        "user_account_audit_events",
        "before_role IS NULL OR before_role IN "
        "('ADMIN', 'ASSISTANT_ADMIN', 'MEMBER', 'STUDENT', 'TEACHER')",
    )
    op.add_column(
        "student_academic_records",
        sa.Column("owner_user_account_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "student_academic_records",
        sa.Column("managed_by_user_account_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        op.f("fk_student_academic_records_owner_user_account_id_user_accounts"),
        "student_academic_records",
        "user_accounts",
        ["owner_user_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_student_academic_records_managed_by_user_account_id_user_accounts"),
        "student_academic_records",
        "user_accounts",
        ["managed_by_user_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_student_academic_records_owner_user_account_id"),
        "student_academic_records",
        ["owner_user_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_student_academic_records_managed_by_user_account_id"),
        "student_academic_records",
        ["managed_by_user_account_id"],
        unique=False,
    )
    op.create_table(
        "verified_source_rule_confirmations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rule_id", sa.String(length=160), nullable=False),
        sa.Column("rule_version", sa.String(length=120), nullable=False),
        sa.Column("source_digest", sa.String(length=64), nullable=False),
        sa.Column("confirmed_by_user_account_id", sa.String(length=36), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
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
            "char_length(source_digest) = 64",
            name=op.f("ck_verified_source_rule_confirmations_source_digest_length"),
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_user_account_id"],
            ["user_accounts.id"],
            name=op.f(
                "fk_verified_source_rule_confirmations_confirmed_by_user_account_id_user_accounts"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verified_source_rule_confirmations")),
        sa.UniqueConstraint(
            "rule_id",
            "rule_version",
            name=op.f("uq_verified_source_rule_confirmations_rule_id"),
        ),
    )
    op.create_index(
        op.f("ix_verified_source_rule_confirmations_rule_id"),
        "verified_source_rule_confirmations",
        ["rule_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_verified_source_rule_confirmations_confirmed_by_user_account_id"),
        "verified_source_rule_confirmations",
        ["confirmed_by_user_account_id"],
        unique=False,
    )
    op.create_table(
        "saved_consultations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("calculation_id", sa.String(length=64), nullable=False),
        sa.Column("student_reference", sa.String(length=120), nullable=False),
        sa.Column("owner_user_account_id", sa.String(length=36), nullable=True),
        sa.Column("managed_by_user_account_id", sa.String(length=36), nullable=True),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("selected_targets", sa.JSON(), nullable=False),
        sa.Column("result_snapshot", sa.JSON(), nullable=False),
        sa.Column("student_print_snapshot", sa.JSON(), nullable=False),
        sa.Column("teacher_print_snapshot", sa.JSON(), nullable=False),
        sa.Column("counselor_note", sa.Text(), nullable=True),
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
            "academic_year BETWEEN 2000 AND 2100",
            name=op.f("ck_saved_consultations_academic_year_valid"),
        ),
        sa.CheckConstraint(
            "(owner_user_account_id IS NOT NULL AND managed_by_user_account_id IS NULL) OR "
            "(owner_user_account_id IS NULL AND managed_by_user_account_id IS NOT NULL)",
            name=op.f("ck_saved_consultations_exactly_one_account_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["managed_by_user_account_id"],
            ["user_accounts.id"],
            name=op.f("fk_saved_consultations_managed_by_user_account_id_user_accounts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_account_id"],
            ["user_accounts.id"],
            name=op.f("fk_saved_consultations_owner_user_account_id_user_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_consultations")),
        sa.UniqueConstraint("calculation_id", name=op.f("uq_saved_consultations_calculation_id")),
    )
    for column in (
        "student_reference",
        "owner_user_account_id",
        "managed_by_user_account_id",
        "academic_year",
    ):
        op.create_index(
            op.f(f"ix_saved_consultations_{column}"),
            "saved_consultations",
            [column],
            unique=False,
        )
    op.drop_constraint(
        op.f("ck_user_account_audit_events_after_role_valid"),
        "user_account_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_user_account_audit_events_after_role_valid"),
        "user_account_audit_events",
        "after_role IS NULL OR after_role IN "
        "('ADMIN', 'ASSISTANT_ADMIN', 'MEMBER', 'STUDENT', 'TEACHER')",
    )
    op.create_table(
        "admission_result_import_datasets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_code", sa.String(length=120), nullable=False),
        sa.Column("source_dataset_version", sa.String(length=120), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=False),
        sa.Column("source_format", sa.String(length=10), nullable=False),
        sa.Column("result_academic_year", sa.Integer(), nullable=False),
        sa.Column("target_academic_year", sa.Integer(), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=30), nullable=False),
        sa.Column("original_row_count", sa.Integer(), nullable=False),
        sa.Column("valid_row_count", sa.Integer(), nullable=False),
        sa.Column("review_row_count", sa.Integer(), nullable=False),
        sa.Column("error_row_count", sa.Integer(), nullable=False),
        sa.Column("published_row_count", sa.Integer(), nullable=False),
        sa.Column("detected_sheets", sa.JSON(), nullable=False),
        sa.Column("column_mapping", sa.JSON(), nullable=False),
        sa.Column("column_mapping_overrides", sa.JSON(), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.String(length=120), nullable=True),
        sa.Column("supersedes_id", sa.String(length=36), nullable=True),
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
            "char_length(source_hash) = 64",
            name=op.f("ck_admission_result_import_datasets_source_hash_length"),
        ),
        sa.CheckConstraint(
            "result_academic_year >= 2000",
            name=op.f("ck_admission_result_import_datasets_result_year_valid"),
        ),
        sa.CheckConstraint(
            "target_academic_year >= 2000",
            name=op.f("ck_admission_result_import_datasets_target_year_valid"),
        ),
        sa.CheckConstraint(
            "source_format IN ('CSV', 'XLSX')",
            name=op.f("ck_admission_result_import_datasets_source_format_valid"),
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('STAGED', 'READY', 'PUBLISHED', 'SUPERSEDED', 'BLOCKED')",
            name=op.f("ck_admission_result_import_datasets_lifecycle_status_valid"),
        ),
        sa.CheckConstraint(
            "original_row_count > 0",
            name=op.f("ck_admission_result_import_datasets_original_row_count_positive"),
        ),
        sa.CheckConstraint(
            "valid_row_count >= 0",
            name=op.f("ck_admission_result_import_datasets_valid_row_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "review_row_count >= 0",
            name=op.f("ck_admission_result_import_datasets_review_row_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "error_row_count >= 0",
            name=op.f("ck_admission_result_import_datasets_error_row_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "published_row_count >= 0",
            name=op.f("ck_admission_result_import_datasets_published_row_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "original_row_count = valid_row_count + review_row_count + error_row_count",
            name=op.f("ck_admission_result_import_datasets_preview_row_counts_consistent"),
        ),
        sa.CheckConstraint(
            "published_row_count <= valid_row_count",
            name=op.f("ck_admission_result_import_datasets_published_not_above_valid"),
        ),
        sa.CheckConstraint(
            "lifecycle_status != 'PUBLISHED' OR (published_at IS NOT NULL AND published_by IS NOT NULL AND published_row_count > 0)",
            name=op.f("ck_admission_result_import_datasets_published_metadata_present"),
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["admission_result_import_datasets.id"],
            name=op.f(
                "fk_admission_result_import_datasets_supersedes_id_admission_result_import_datasets"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admission_result_import_datasets")),
        sa.UniqueConstraint(
            "source_hash", name=op.f("uq_admission_result_import_datasets_source_hash")
        ),
    )
    for column in ("source_code", "result_academic_year", "target_academic_year"):
        op.create_index(
            op.f(f"ix_admission_result_import_datasets_{column}"),
            "admission_result_import_datasets",
            [column],
            unique=False,
        )

    op.create_table(
        "admission_result_import_rows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("source_sheet", sa.String(length=200), nullable=False),
        sa.Column("result_academic_year", sa.Integer(), nullable=False),
        sa.Column("target_academic_year", sa.Integer(), nullable=False),
        sa.Column("region", sa.String(length=80), nullable=True),
        sa.Column("institution_code", sa.String(length=80), nullable=True),
        sa.Column("institution_name", sa.String(length=200), nullable=False),
        sa.Column("campus_code", sa.String(length=80), nullable=True),
        sa.Column("campus_name", sa.String(length=200), nullable=True),
        sa.Column("program_code", sa.String(length=120), nullable=True),
        sa.Column("program_name", sa.String(length=200), nullable=False),
        sa.Column("admission_round_code", sa.String(length=80), nullable=True),
        sa.Column("admission_round_name", sa.String(length=200), nullable=False),
        sa.Column("day_night", sa.String(length=40), nullable=True),
        sa.Column("admission_category", sa.String(length=120), nullable=True),
        sa.Column("admission_track_code", sa.String(length=80), nullable=True),
        sa.Column("admission_track_name", sa.String(length=200), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("applicant_count", sa.Integer(), nullable=True),
        sa.Column("admitted_count", sa.Integer(), nullable=True),
        sa.Column("competition_rate", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("best_score", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("average_score", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("cutoff_score", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("score_basis", sa.String(length=80), nullable=False),
        sa.Column("score_direction", sa.String(length=40), nullable=False),
        sa.Column("historical_score_rule_id", sa.String(length=36), nullable=True),
        sa.Column("historical_score_rule_version", sa.String(length=120), nullable=True),
        sa.Column("historical_score_rule_year", sa.Integer(), nullable=True),
        sa.Column("source_reference", sa.String(length=500), nullable=False),
        sa.Column("validation_status", sa.String(length=20), nullable=False),
        sa.Column("validation_issues", sa.JSON(), nullable=False),
        sa.Column("publication_status", sa.String(length=20), nullable=False),
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
            "source_row_number > 0",
            name=op.f("ck_admission_result_import_rows_source_row_number_positive"),
        ),
        sa.CheckConstraint(
            "result_academic_year >= 2000",
            name=op.f("ck_admission_result_import_rows_result_year_valid"),
        ),
        sa.CheckConstraint(
            "target_academic_year >= 2000",
            name=op.f("ck_admission_result_import_rows_target_year_valid"),
        ),
        sa.CheckConstraint(
            "validation_status IN ('VALID', 'REVIEW', 'ERROR')",
            name=op.f("ck_admission_result_import_rows_validation_status_valid"),
        ),
        sa.CheckConstraint(
            "publication_status IN ('STAGED', 'PUBLISHED', 'SUPERSEDED', 'EXCLUDED')",
            name=op.f("ck_admission_result_import_rows_publication_status_valid"),
        ),
        sa.CheckConstraint(
            "capacity IS NULL OR capacity >= 0",
            name=op.f("ck_admission_result_import_rows_capacity_valid"),
        ),
        sa.CheckConstraint(
            "applicant_count IS NULL OR applicant_count >= 0",
            name=op.f("ck_admission_result_import_rows_applicants_valid"),
        ),
        sa.CheckConstraint(
            "admitted_count IS NULL OR admitted_count >= 0",
            name=op.f("ck_admission_result_import_rows_admitted_valid"),
        ),
        sa.CheckConstraint(
            "competition_rate IS NULL OR competition_rate >= 0",
            name=op.f("ck_admission_result_import_rows_competition_valid"),
        ),
        sa.CheckConstraint(
            "best_score IS NULL OR best_score >= 0",
            name=op.f("ck_admission_result_import_rows_best_score_valid"),
        ),
        sa.CheckConstraint(
            "average_score IS NULL OR average_score >= 0",
            name=op.f("ck_admission_result_import_rows_average_score_valid"),
        ),
        sa.CheckConstraint(
            "cutoff_score IS NULL OR cutoff_score >= 0",
            name=op.f("ck_admission_result_import_rows_cutoff_score_valid"),
        ),
        sa.CheckConstraint(
            "validation_status != 'VALID' OR (institution_code IS NOT NULL AND campus_code IS NOT NULL AND program_code IS NOT NULL AND admission_round_code IS NOT NULL AND admission_track_code IS NOT NULL)",
            name=op.f("ck_admission_result_import_rows_valid_row_has_business_key"),
        ),
        sa.CheckConstraint(
            "publication_status != 'PUBLISHED' OR "
            "(score_basis = 'RANK_GRADE' AND score_direction = 'LOWER_IS_BETTER' "
            "AND (best_score IS NULL OR best_score BETWEEN 1 AND 9) "
            "AND (average_score IS NULL OR average_score BETWEEN 1 AND 9) "
            "AND (cutoff_score IS NULL OR cutoff_score BETWEEN 1 AND 9))",
            name=op.f("ck_admission_result_import_rows_published_rank_grade_scale_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["admission_result_import_datasets.id"],
            name=op.f(
                "fk_admission_result_import_rows_dataset_id_admission_result_import_datasets"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admission_result_import_rows")),
        sa.UniqueConstraint(
            "dataset_id",
            "source_sheet",
            "source_row_number",
            name=op.f("uq_admission_result_import_rows_dataset_id"),
        ),
    )
    for column in ("dataset_id", "result_academic_year", "target_academic_year"):
        op.create_index(
            op.f(f"ix_admission_result_import_rows_{column}"),
            "admission_result_import_rows",
            [column],
            unique=False,
        )
    op.create_index(
        "uq_admission_result_import_rows_published_business_key",
        "admission_result_import_rows",
        [
            "target_academic_year",
            "result_academic_year",
            "institution_code",
            "campus_code",
            "program_code",
            "admission_round_code",
            "admission_track_code",
            "score_basis",
        ],
        unique=True,
        postgresql_where=sa.text("publication_status = 'PUBLISHED'"),
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_verified_source_rule_confirmations_confirmed_by_user_account_id"),
        table_name="verified_source_rule_confirmations",
    )
    op.drop_index(
        op.f("ix_verified_source_rule_confirmations_rule_id"),
        table_name="verified_source_rule_confirmations",
    )
    op.drop_table("verified_source_rule_confirmations")
    for column in (
        "academic_year",
        "managed_by_user_account_id",
        "owner_user_account_id",
        "student_reference",
    ):
        op.drop_index(
            op.f(f"ix_saved_consultations_{column}"),
            table_name="saved_consultations",
        )
    op.drop_table("saved_consultations")
    op.drop_index(
        "uq_admission_result_import_rows_published_business_key",
        table_name="admission_result_import_rows",
    )
    for column in ("target_academic_year", "result_academic_year", "dataset_id"):
        op.drop_index(
            op.f(f"ix_admission_result_import_rows_{column}"),
            table_name="admission_result_import_rows",
        )
    op.drop_table("admission_result_import_rows")
    for column in ("target_academic_year", "result_academic_year", "source_code"):
        op.drop_index(
            op.f(f"ix_admission_result_import_datasets_{column}"),
            table_name="admission_result_import_datasets",
        )
    op.drop_table("admission_result_import_datasets")
    op.drop_index(
        op.f("ix_student_academic_records_managed_by_user_account_id"),
        table_name="student_academic_records",
    )
    op.drop_index(
        op.f("ix_student_academic_records_owner_user_account_id"),
        table_name="student_academic_records",
    )
    op.drop_constraint(
        op.f("fk_student_academic_records_managed_by_user_account_id_user_accounts"),
        "student_academic_records",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_student_academic_records_owner_user_account_id_user_accounts"),
        "student_academic_records",
        type_="foreignkey",
    )
    op.drop_column("student_academic_records", "managed_by_user_account_id")
    op.drop_column("student_academic_records", "owner_user_account_id")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM user_accounts WHERE role IN ('STUDENT', 'TEACHER')) "
        "OR EXISTS (SELECT 1 FROM user_account_audit_events "
        "WHERE before_role IN ('STUDENT', 'TEACHER') OR after_role IN ('STUDENT', 'TEACHER')) "
        "THEN RAISE EXCEPTION 'STUDENT/TEACHER 역할 데이터가 있어 안전하게 downgrade할 수 없습니다'; "
        "END IF; END $$"
    )
    op.drop_constraint(
        op.f("ck_user_account_audit_events_after_role_valid"),
        "user_account_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_user_account_audit_events_after_role_valid"),
        "user_account_audit_events",
        "after_role IS NULL OR after_role IN ('ADMIN', 'ASSISTANT_ADMIN', 'MEMBER')",
    )
    op.drop_constraint(
        op.f("ck_user_account_audit_events_before_role_valid"),
        "user_account_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_user_account_audit_events_before_role_valid"),
        "user_account_audit_events",
        "before_role IS NULL OR before_role IN ('ADMIN', 'ASSISTANT_ADMIN', 'MEMBER')",
    )
    op.drop_constraint(
        op.f("ck_user_accounts_pending_role_member"),
        "user_accounts",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_user_accounts_pending_role_member"),
        "user_accounts",
        "status NOT IN ('PENDING_APPROVAL', 'REJECTED') OR role = 'MEMBER'",
    )
    op.drop_constraint(op.f("ck_user_accounts_role_valid"), "user_accounts", type_="check")
    op.create_check_constraint(
        op.f("ck_user_accounts_role_valid"),
        "user_accounts",
        "role IN ('ADMIN', 'ASSISTANT_ADMIN', 'MEMBER')",
    )
