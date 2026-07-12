"""Phase 6 입시결과 수집 계약

Revision ID: f4c2a91d6e73
Revises: c8a4b2f719d0
Create Date: 2026-07-13 07:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4c2a91d6e73"
down_revision: str | None = "c8a4b2f719d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admission_result_raw_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_code", sa.String(length=120), nullable=False),
        sa.Column("expected_academic_year", sa.Integer(), nullable=False),
        sa.Column("collection_digest", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("policy_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False),
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
            "expected_academic_year >= 2000",
            name=op.f("ck_admission_result_raw_batches_academic_year_valid"),
        ),
        sa.CheckConstraint(
            "char_length(collection_digest) = 64",
            name=op.f("ck_admission_result_raw_batches_digest_length"),
        ),
        sa.CheckConstraint(
            "page_count > 0", name=op.f("ck_admission_result_raw_batches_page_count_positive")
        ),
        sa.CheckConstraint(
            "row_count > 0", name=op.f("ck_admission_result_raw_batches_row_count_positive")
        ),
        sa.CheckConstraint(
            "status = 'COLLECTED'", name=op.f("ck_admission_result_raw_batches_status_valid")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admission_result_raw_batches")),
        sa.UniqueConstraint(
            "collection_digest", name=op.f("uq_admission_result_raw_batches_collection_digest")
        ),
    )
    op.create_index(
        op.f("ix_admission_result_raw_batches_expected_academic_year"),
        "admission_result_raw_batches",
        ["expected_academic_year"],
    )
    op.create_index(
        op.f("ix_admission_result_raw_batches_source_code"),
        "admission_result_raw_batches",
        ["source_code"],
    )
    op.create_table(
        "admission_result_raw_pages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("raw_batch_id", sa.String(length=36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response_digest", sa.String(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("raw_rows", sa.JSON(), nullable=False),
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
            "page_number > 0", name=op.f("ck_admission_result_raw_pages_page_number_positive")
        ),
        sa.CheckConstraint(
            "row_count >= 0", name=op.f("ck_admission_result_raw_pages_row_count_nonnegative")
        ),
        sa.CheckConstraint(
            "char_length(request_fingerprint) = 64",
            name=op.f("ck_admission_result_raw_pages_request_hash_length"),
        ),
        sa.CheckConstraint(
            "char_length(response_digest) = 64",
            name=op.f("ck_admission_result_raw_pages_response_hash_length"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_batch_id"],
            ["admission_result_raw_batches.id"],
            name=op.f("fk_admission_result_raw_pages_raw_batch_id_admission_result_raw_batches"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admission_result_raw_pages")),
        sa.UniqueConstraint(
            "raw_batch_id",
            "page_number",
            name=op.f("uq_admission_result_raw_pages_raw_batch_id"),
        ),
    )
    op.create_index(
        op.f("ix_admission_result_raw_pages_raw_batch_id"),
        "admission_result_raw_pages",
        ["raw_batch_id"],
    )
    op.create_table(
        "admission_result_staging_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("raw_batch_id", sa.String(length=36), nullable=False),
        sa.Column("expected_academic_year", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("total_row_count", sa.Integer(), nullable=False),
        sa.Column("valid_row_count", sa.Integer(), nullable=False),
        sa.Column("error_row_count", sa.Integer(), nullable=False),
        sa.Column("validation_issues", sa.JSON(), nullable=False),
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
            "expected_academic_year >= 2000",
            name=op.f("ck_admission_result_staging_batches_academic_year_valid"),
        ),
        sa.CheckConstraint(
            "total_row_count > 0",
            name=op.f("ck_admission_result_staging_batches_total_row_count_positive"),
        ),
        sa.CheckConstraint(
            "valid_row_count >= 0",
            name=op.f("ck_admission_result_staging_batches_valid_row_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "error_row_count >= 0",
            name=op.f("ck_admission_result_staging_batches_error_row_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "total_row_count = valid_row_count + error_row_count",
            name=op.f("ck_admission_result_staging_batches_row_counts_consistent"),
        ),
        sa.CheckConstraint(
            "status IN ('READY', 'BLOCKED')",
            name=op.f("ck_admission_result_staging_batches_status_valid"),
        ),
        sa.CheckConstraint(
            "status != 'READY' OR (error_row_count = 0 AND valid_row_count = total_row_count)",
            name=op.f("ck_admission_result_staging_batches_ready_batch_has_no_errors"),
        ),
        sa.ForeignKeyConstraint(
            ["raw_batch_id"],
            ["admission_result_raw_batches.id"],
            name=op.f(
                "fk_admission_result_staging_batches_raw_batch_id_admission_result_raw_batches"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admission_result_staging_batches")),
        sa.UniqueConstraint(
            "raw_batch_id", name=op.f("uq_admission_result_staging_batches_raw_batch_id")
        ),
    )
    op.create_index(
        op.f("ix_admission_result_staging_batches_expected_academic_year"),
        "admission_result_staging_batches",
        ["expected_academic_year"],
    )
    op.create_table(
        "admission_result_staging_rows",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("staging_batch_id", sa.String(length=36), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=True),
        sa.Column("university_code", sa.String(length=80), nullable=True),
        sa.Column("campus_code", sa.String(length=80), nullable=True),
        sa.Column("admission_round", sa.String(length=80), nullable=True),
        sa.Column("admission_track_code", sa.String(length=80), nullable=True),
        sa.Column("program_code", sa.String(length=120), nullable=True),
        sa.Column("applicant_count", sa.Integer(), nullable=True),
        sa.Column("admitted_count", sa.Integer(), nullable=True),
        sa.Column("competition_rate", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("highest_score", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("average_score", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("lowest_score", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("score_basis", sa.String(length=80), nullable=True),
        sa.Column("validation_status", sa.String(length=30), nullable=False),
        sa.Column("validation_issues", sa.JSON(), nullable=False),
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
            name=op.f("ck_admission_result_staging_rows_source_row_number_positive"),
        ),
        sa.CheckConstraint(
            "academic_year IS NULL OR academic_year >= 2000",
            name=op.f("ck_admission_result_staging_rows_year_valid"),
        ),
        sa.CheckConstraint(
            "validation_status IN ('VALID', 'ERROR')",
            name=op.f("ck_admission_result_staging_rows_status_valid"),
        ),
        sa.CheckConstraint(
            "validation_status != 'VALID' OR (academic_year IS NOT NULL "
            "AND university_code IS NOT NULL AND campus_code IS NOT NULL "
            "AND admission_round IS NOT NULL AND admission_track_code IS NOT NULL "
            "AND program_code IS NOT NULL)",
            name=op.f("ck_admission_result_staging_rows_valid_row_has_business_key"),
        ),
        sa.CheckConstraint(
            "applicant_count IS NULL OR applicant_count >= 0",
            name=op.f("ck_admission_result_staging_rows_applicants_valid"),
        ),
        sa.CheckConstraint(
            "admitted_count IS NULL OR admitted_count >= 0",
            name=op.f("ck_admission_result_staging_rows_admitted_valid"),
        ),
        sa.CheckConstraint(
            "competition_rate IS NULL OR competition_rate >= 0",
            name=op.f("ck_admission_result_staging_rows_competition_rate_valid"),
        ),
        sa.CheckConstraint(
            "highest_score IS NULL OR highest_score >= 0",
            name=op.f("ck_admission_result_staging_rows_highest_score_valid"),
        ),
        sa.CheckConstraint(
            "average_score IS NULL OR average_score >= 0",
            name=op.f("ck_admission_result_staging_rows_average_score_valid"),
        ),
        sa.CheckConstraint(
            "lowest_score IS NULL OR lowest_score >= 0",
            name=op.f("ck_admission_result_staging_rows_lowest_score_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["staging_batch_id"],
            ["admission_result_staging_batches.id"],
            name=op.f(
                "fk_admission_result_staging_rows_staging_batch_id_admission_result_staging_batches"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admission_result_staging_rows")),
        sa.UniqueConstraint(
            "staging_batch_id",
            "academic_year",
            "university_code",
            "campus_code",
            "admission_round",
            "admission_track_code",
            "program_code",
            name="uq_admission_result_staging_rows_business_key",
        ),
        sa.UniqueConstraint(
            "staging_batch_id",
            "source_row_number",
            name="uq_admission_result_staging_rows_source_row",
        ),
    )
    op.create_index(
        op.f("ix_admission_result_staging_rows_staging_batch_id"),
        "admission_result_staging_rows",
        ["staging_batch_id"],
    )
    op.create_table(
        "admission_result_published_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("staging_batch_id", sa.String(length=36), nullable=False),
        sa.Column("approved_by", sa.String(length=120), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_row_count", sa.Integer(), nullable=False),
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
            "confirmed_row_count > 0",
            name=op.f("ck_admission_result_published_batches_confirmed_row_count_positive"),
        ),
        sa.CheckConstraint(
            "char_length(approved_by) > 0",
            name=op.f("ck_admission_result_published_batches_approved_by_present"),
        ),
        sa.ForeignKeyConstraint(
            ["staging_batch_id"],
            ["admission_result_staging_batches.id"],
            name=op.f(
                "fk_admission_result_published_batches_staging_batch_id_admission_result_staging_batches"
            ),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admission_result_published_batches")),
        sa.UniqueConstraint(
            "staging_batch_id", name=op.f("uq_admission_result_published_batches_staging_batch_id")
        ),
    )
    op.create_table(
        "admission_results_published",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("published_batch_id", sa.String(length=36), nullable=False),
        sa.Column("staging_row_id", sa.String(length=36), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("university_code", sa.String(length=80), nullable=False),
        sa.Column("campus_code", sa.String(length=80), nullable=False),
        sa.Column("admission_round", sa.String(length=80), nullable=False),
        sa.Column("admission_track_code", sa.String(length=80), nullable=False),
        sa.Column("program_code", sa.String(length=120), nullable=False),
        sa.Column("publication_version", sa.String(length=120), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=30), nullable=False),
        sa.Column("supersedes_id", sa.String(length=36), nullable=True),
        sa.Column("applicant_count", sa.Integer(), nullable=True),
        sa.Column("admitted_count", sa.Integer(), nullable=True),
        sa.Column("competition_rate", sa.Numeric(precision=12, scale=4), nullable=True),
        sa.Column("highest_score", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("average_score", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("lowest_score", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("score_basis", sa.String(length=80), nullable=True),
        sa.Column("score_rule_id", sa.String(length=36), nullable=True),
        sa.Column("score_rule_version", sa.String(length=120), nullable=True),
        sa.Column("score_rule_academic_year", sa.Integer(), nullable=True),
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
            "academic_year >= 2000",
            name=op.f("ck_admission_results_published_academic_year_valid"),
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('PUBLISHED', 'SUPERSEDED')",
            name=op.f("ck_admission_results_published_status_valid"),
        ),
        sa.CheckConstraint(
            "applicant_count IS NULL OR applicant_count >= 0",
            name=op.f("ck_admission_results_published_applicants_valid"),
        ),
        sa.CheckConstraint(
            "admitted_count IS NULL OR admitted_count >= 0",
            name=op.f("ck_admission_results_published_admitted_valid"),
        ),
        sa.CheckConstraint(
            "competition_rate IS NULL OR competition_rate >= 0",
            name=op.f("ck_admission_results_published_competition_rate_valid"),
        ),
        sa.CheckConstraint(
            "highest_score IS NULL OR highest_score >= 0",
            name=op.f("ck_admission_results_published_highest_score_valid"),
        ),
        sa.CheckConstraint(
            "average_score IS NULL OR average_score >= 0",
            name=op.f("ck_admission_results_published_average_score_valid"),
        ),
        sa.CheckConstraint(
            "lowest_score IS NULL OR lowest_score >= 0",
            name=op.f("ck_admission_results_published_lowest_score_valid"),
        ),
        sa.CheckConstraint(
            "(score_rule_id IS NULL AND score_rule_version IS NULL "
            "AND score_rule_academic_year IS NULL) OR "
            "(score_rule_id IS NOT NULL AND score_rule_version IS NOT NULL "
            "AND score_rule_academic_year = academic_year)",
            name=op.f("ck_admission_results_published_historical_rule_version_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["published_batch_id"],
            ["admission_result_published_batches.id"],
            name=op.f(
                "fk_admission_results_published_published_batch_id_admission_result_published_batches"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["score_rule_id"],
            ["score_rules.id"],
            name=op.f("fk_admission_results_published_score_rule_id_score_rules"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["staging_row_id"],
            ["admission_result_staging_rows.id"],
            name=op.f(
                "fk_admission_results_published_staging_row_id_admission_result_staging_rows"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["admission_results_published.id"],
            name=op.f("fk_admission_results_published_supersedes_id_admission_results_published"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admission_results_published")),
        sa.UniqueConstraint(
            "academic_year",
            "university_code",
            "campus_code",
            "admission_round",
            "admission_track_code",
            "program_code",
            "publication_version",
            name=op.f("uq_admission_results_published_academic_year"),
        ),
        sa.UniqueConstraint(
            "staging_row_id", name=op.f("uq_admission_results_published_staging_row_id")
        ),
    )
    op.create_index(
        op.f("ix_admission_results_published_academic_year"),
        "admission_results_published",
        ["academic_year"],
    )
    op.create_index(
        op.f("ix_admission_results_published_published_batch_id"),
        "admission_results_published",
        ["published_batch_id"],
    )
    op.create_index(
        op.f("ix_admission_results_published_score_rule_id"),
        "admission_results_published",
        ["score_rule_id"],
    )
    op.create_index(
        "uq_admission_results_one_published_per_business_key",
        "admission_results_published",
        [
            "academic_year",
            "university_code",
            "campus_code",
            "admission_round",
            "admission_track_code",
            "program_code",
        ],
        unique=True,
        postgresql_where=sa.text("lifecycle_status = 'PUBLISHED'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_admission_results_one_published_per_business_key",
        table_name="admission_results_published",
    )
    op.drop_index(
        op.f("ix_admission_results_published_score_rule_id"),
        table_name="admission_results_published",
    )
    op.drop_index(
        op.f("ix_admission_results_published_published_batch_id"),
        table_name="admission_results_published",
    )
    op.drop_index(
        op.f("ix_admission_results_published_academic_year"),
        table_name="admission_results_published",
    )
    op.drop_table("admission_results_published")
    op.drop_table("admission_result_published_batches")
    op.drop_index(
        op.f("ix_admission_result_staging_rows_staging_batch_id"),
        table_name="admission_result_staging_rows",
    )
    op.drop_table("admission_result_staging_rows")
    op.drop_index(
        op.f("ix_admission_result_staging_batches_expected_academic_year"),
        table_name="admission_result_staging_batches",
    )
    op.drop_table("admission_result_staging_batches")
    op.drop_index(
        op.f("ix_admission_result_raw_pages_raw_batch_id"),
        table_name="admission_result_raw_pages",
    )
    op.drop_table("admission_result_raw_pages")
    op.drop_index(
        op.f("ix_admission_result_raw_batches_source_code"),
        table_name="admission_result_raw_batches",
    )
    op.drop_index(
        op.f("ix_admission_result_raw_batches_expected_academic_year"),
        table_name="admission_result_raw_batches",
    )
    op.drop_table("admission_result_raw_batches")
