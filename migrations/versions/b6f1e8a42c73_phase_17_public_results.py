"""Phase 17 public results distinguish campus region, day/night and score scale."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6f1e8a42c73"
down_revision: str | None = "8e31b7c4d2a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "saved_consultations",
        sa.Column(
            "student_profile",
            sa.String(length=40),
            server_default=sa.text("'VOCATIONAL_CURRENT'"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_saved_consultations_student_profile_valid"),
        "saved_consultations",
        "student_profile IN ('VOCATIONAL_CURRENT', 'GENERAL_GRADUATE')",
    )

    op.add_column("campuses", sa.Column("region", sa.String(length=80), nullable=True))
    op.create_index(
        "ix_campuses_institution_id_region",
        "campuses",
        ["institution_id", "region"],
        unique=False,
    )

    op.add_column(
        "programs",
        sa.Column(
            "day_night",
            sa.String(length=20),
            server_default=sa.text("'UNKNOWN'"),
            nullable=False,
        ),
    )
    op.drop_constraint("uq_programs_campus_id", "programs", type_="unique")
    op.create_unique_constraint(
        "uq_programs_campus_name_day_night",
        "programs",
        ["campus_id", "name", "day_night"],
    )
    op.create_check_constraint(
        op.f("ck_programs_day_night_valid"),
        "programs",
        "day_night IN ('DAY', 'NIGHT', 'UNKNOWN')",
    )

    op.execute(
        """
        UPDATE admission_result_import_rows
        SET day_night = CASE
            WHEN day_night = '주간' THEN 'DAY'
            WHEN day_night = '야간' THEN 'NIGHT'
            WHEN day_night IS NULL OR btrim(day_night) = '' THEN 'UNKNOWN'
            ELSE day_night
        END
        """
    )
    op.alter_column(
        "admission_result_import_rows",
        "day_night",
        existing_type=sa.String(length=40),
        nullable=False,
        server_default=sa.text("'UNKNOWN'"),
    )
    op.create_check_constraint(
        op.f("ck_admission_result_import_rows_day_night_valid"),
        "admission_result_import_rows",
        "day_night IN ('DAY', 'NIGHT', 'UNKNOWN')",
    )
    op.drop_constraint(
        op.f("ck_admission_result_import_rows_published_rank_grade_scale_valid"),
        "admission_result_import_rows",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_admission_result_import_rows_published_score_scale_valid"),
        "admission_result_import_rows",
        "publication_status != 'PUBLISHED' OR "
        "((score_basis IN ('RANK_GRADE', 'CSAT_GRADE') "
        "AND score_direction = 'LOWER_IS_BETTER' "
        "AND (best_score IS NULL OR best_score BETWEEN 1 AND 9) "
        "AND (average_score IS NULL OR average_score BETWEEN 1 AND 9) "
        "AND (cutoff_score IS NULL OR cutoff_score BETWEEN 1 AND 9)) OR "
        "(score_basis = 'POINT_SCORE' AND score_direction = 'HIGHER_IS_BETTER'))",
    )
    op.drop_index(
        "uq_admission_result_import_rows_published_business_key",
        table_name="admission_result_import_rows",
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
            "day_night",
            "score_basis",
        ],
        unique=True,
        postgresql_where=sa.text("publication_status = 'PUBLISHED'"),
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM admission_result_import_rows
            WHERE publication_status = 'PUBLISHED'
              AND score_basis <> 'RANK_GRADE'
          ) THEN
            RAISE EXCEPTION 'Phase 17 non-rank published results must be removed before downgrade';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM admission_result_import_rows
            WHERE publication_status = 'PUBLISHED'
            GROUP BY target_academic_year, result_academic_year, institution_code,
                     campus_code, program_code, admission_round_code,
                     admission_track_code, score_basis
            HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION 'Phase 17 day/night result keys must be resolved before downgrade';
          END IF;
          IF EXISTS (
            SELECT 1 FROM programs
            GROUP BY campus_id, name
            HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION 'Phase 17 day/night programs must be resolved before downgrade';
          END IF;
        END $$
        """
    )
    op.drop_index(
        "uq_admission_result_import_rows_published_business_key",
        table_name="admission_result_import_rows",
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
    op.drop_constraint(
        op.f("ck_admission_result_import_rows_published_score_scale_valid"),
        "admission_result_import_rows",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_admission_result_import_rows_published_rank_grade_scale_valid"),
        "admission_result_import_rows",
        "publication_status != 'PUBLISHED' OR "
        "(score_basis = 'RANK_GRADE' AND score_direction = 'LOWER_IS_BETTER' "
        "AND (best_score IS NULL OR best_score BETWEEN 1 AND 9) "
        "AND (average_score IS NULL OR average_score BETWEEN 1 AND 9) "
        "AND (cutoff_score IS NULL OR cutoff_score BETWEEN 1 AND 9))",
    )
    op.drop_constraint(
        op.f("ck_admission_result_import_rows_day_night_valid"),
        "admission_result_import_rows",
        type_="check",
    )
    op.alter_column(
        "admission_result_import_rows",
        "day_night",
        existing_type=sa.String(length=40),
        nullable=True,
        server_default=None,
    )
    op.execute(
        """
        UPDATE admission_result_import_rows
        SET day_night = CASE
            WHEN day_night = 'DAY' THEN '주간'
            WHEN day_night = 'NIGHT' THEN '야간'
            WHEN day_night = 'UNKNOWN' THEN NULL
            ELSE day_night
        END
        """
    )

    op.drop_constraint(op.f("ck_programs_day_night_valid"), "programs", type_="check")
    op.drop_constraint("uq_programs_campus_name_day_night", "programs", type_="unique")
    op.create_unique_constraint("uq_programs_campus_id", "programs", ["campus_id", "name"])
    op.drop_column("programs", "day_night")
    op.drop_index("ix_campuses_institution_id_region", table_name="campuses")
    op.drop_column("campuses", "region")
    op.drop_constraint(
        op.f("ck_saved_consultations_student_profile_valid"),
        "saved_consultations",
        type_="check",
    )
    op.drop_column("saved_consultations", "student_profile")
