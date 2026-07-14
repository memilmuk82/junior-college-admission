"""Phase 10 canonical 게시 게이트

Revision ID: 0d9f4a7c2b11
Revises: f76a91c3d2e8
Create Date: 2026-07-15 06:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0d9f4a7c2b11"
down_revision: str | None = "f76a91c3d2e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RULE_TABLE_TYPES_WITH_GOLDEN_ARTIFACT = (
    ("admission_eligibility_rules", "ADMISSION_ELIGIBILITY_RULE"),
    ("grade_source_scope_rules", "GRADE_SOURCE_SCOPE_RULE"),
    ("score_rules", "SCORE_RULE"),
    ("multiple_application_rules", "MULTIPLE_APPLICATION_RULE"),
    ("disqualification_rules", "DISQUALIFICATION_RULE"),
    ("score_adjustment_rules", "SCORE_ADJUSTMENT_RULE"),
    ("document_requirements", "DOCUMENT_REQUIREMENT"),
    ("tie_break_rules", "TIE_BREAK_RULE"),
)


def upgrade() -> None:
    legacy_ref_count_query = " UNION ALL ".join(
        f"SELECT count(*) AS ref_count FROM {table_name} WHERE golden_test_ref IS NOT NULL"
        for table_name, _rule_type in RULE_TABLE_TYPES_WITH_GOLDEN_ARTIFACT
    )
    op.execute(
        "DO $$ DECLARE legacy_ref_count bigint; BEGIN "
        "SELECT COALESCE(sum(ref_count), 0) INTO legacy_ref_count FROM ("
        f"{legacy_ref_count_query}"
        ") AS legacy_refs; "
        "IF legacy_ref_count > 0 THEN "
        "RAISE EXCEPTION '검증되지 않은 기존 golden_test_ref %건이 있어 "
        "canonical 게시 게이트 migration을 중단합니다.', legacy_ref_count; "
        "END IF; END $$"
    )
    op.add_column("institutions", sa.Column("code", sa.String(length=80), nullable=True))
    op.create_unique_constraint(
        op.f("uq_institutions_code"),
        "institutions",
        ["code"],
    )
    op.create_check_constraint(
        op.f("ck_institutions_code_valid"),
        "institutions",
        "code IS NULL OR (code = btrim(code) AND char_length(code) > 0)",
    )
    op.add_column("campuses", sa.Column("code", sa.String(length=80), nullable=True))
    op.create_unique_constraint(
        op.f("uq_campuses_institution_id_code"),
        "campuses",
        ["institution_id", "code"],
    )
    op.create_check_constraint(
        op.f("ck_campuses_code_valid"),
        "campuses",
        "code IS NULL OR (code = btrim(code) AND char_length(code) > 0)",
    )
    for table_name, _rule_type in RULE_TABLE_TYPES_WITH_GOLDEN_ARTIFACT:
        op.add_column(
            table_name,
            sa.Column("golden_test_rule_type", sa.String(length=80), nullable=True),
        )
    op.create_unique_constraint(
        op.f("uq_rule_reviews_id_rule_type_rule_id"),
        "rule_reviews",
        ["id", "rule_type", "rule_id"],
    )
    op.create_table(
        "rule_golden_test_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rule_type", sa.String(length=80), nullable=False),
        sa.Column("rule_id", sa.String(length=36), nullable=False),
        sa.Column("independent_review_id", sa.String(length=36), nullable=False),
        sa.Column("artifact_ref", sa.String(length=240), nullable=False),
        sa.Column("artifact_digest", sa.String(length=64), nullable=False),
        sa.Column("suite_ref", sa.String(length=240), nullable=False),
        sa.Column("suite_digest", sa.String(length=64), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("passed_case_count", sa.Integer(), nullable=False),
        sa.Column("failed_case_count", sa.Integer(), nullable=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False),
        sa.Column("contract_digest", sa.String(length=64), nullable=False),
        sa.Column("contract_schema_version", sa.Integer(), nullable=False),
        sa.Column("result_status", sa.String(length=20), nullable=False),
        sa.Column("runner_ref", sa.String(length=120), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False),
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
            "result_status IN ('PASSED', 'FAILED')",
            name=op.f("ck_rule_golden_test_artifacts_result_status_valid"),
        ),
        sa.CheckConstraint(
            "rule_type IN ('ADMISSION_ELIGIBILITY_RULE', 'GRADE_SOURCE_SCOPE_RULE', "
            "'SCORE_RULE', 'MULTIPLE_APPLICATION_RULE', 'DISQUALIFICATION_RULE', "
            "'SCORE_ADJUSTMENT_RULE', 'DOCUMENT_REQUIREMENT', 'TIE_BREAK_RULE')",
            name=op.f("ck_rule_golden_test_artifacts_rule_type_valid"),
        ),
        sa.CheckConstraint(
            "artifact_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_rule_golden_test_artifacts_artifact_digest_valid"),
        ),
        sa.CheckConstraint(
            "payload_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_rule_golden_test_artifacts_payload_digest_valid"),
        ),
        sa.CheckConstraint(
            "contract_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_rule_golden_test_artifacts_contract_digest_valid"),
        ),
        sa.CheckConstraint(
            "contract_schema_version = 2",
            name=op.f("ck_rule_golden_test_artifacts_contract_schema_version_valid"),
        ),
        sa.CheckConstraint(
            "artifact_ref = btrim(artifact_ref) AND char_length(artifact_ref) > 0",
            name=op.f("ck_rule_golden_test_artifacts_artifact_ref_present"),
        ),
        sa.CheckConstraint(
            "substr(artifact_ref, 1, char_length('golden-run/' || rule_type || '/')) "
            "= 'golden-run/' || rule_type || '/'",
            name=op.f("ck_rule_golden_test_artifacts_artifact_ref_rule_type"),
        ),
        sa.CheckConstraint(
            "suite_ref = btrim(suite_ref) AND char_length(suite_ref) > 0",
            name=op.f("ck_rule_golden_test_artifacts_suite_ref_present"),
        ),
        sa.CheckConstraint(
            "suite_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_rule_golden_test_artifacts_suite_digest_valid"),
        ),
        sa.CheckConstraint(
            "case_count > 0",
            name=op.f("ck_rule_golden_test_artifacts_case_count_positive"),
        ),
        sa.CheckConstraint(
            "passed_case_count >= 0 AND failed_case_count >= 0",
            name=op.f("ck_rule_golden_test_artifacts_case_counts_nonnegative"),
        ),
        sa.CheckConstraint(
            "passed_case_count + failed_case_count = case_count",
            name=op.f("ck_rule_golden_test_artifacts_case_counts_complete"),
        ),
        sa.CheckConstraint(
            "(result_status = 'PASSED' AND failed_case_count = 0 "
            "AND passed_case_count = case_count) OR "
            "(result_status = 'FAILED' AND failed_case_count > 0)",
            name=op.f("ck_rule_golden_test_artifacts_result_counts_consistent"),
        ),
        sa.CheckConstraint(
            "runner_ref = btrim(runner_ref) AND char_length(runner_ref) > 0",
            name=op.f("ck_rule_golden_test_artifacts_runner_present"),
        ),
        sa.ForeignKeyConstraint(
            ["independent_review_id", "rule_type", "rule_id"],
            ["rule_reviews.id", "rule_reviews.rule_type", "rule_reviews.rule_id"],
            name=op.f("fk_rule_golden_test_artifacts_independent_review_id_rule_reviews"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rule_golden_test_artifacts")),
        sa.UniqueConstraint(
            "artifact_ref",
            name=op.f("uq_rule_golden_test_artifacts_artifact_ref"),
        ),
        sa.UniqueConstraint(
            "artifact_ref",
            "rule_id",
            name=op.f("uq_rule_golden_test_artifacts_artifact_ref_rule_id"),
        ),
        sa.UniqueConstraint(
            "artifact_ref",
            "rule_id",
            "rule_type",
            name=op.f("uq_rule_golden_test_artifacts_artifact_ref_rule_id_rule_type"),
        ),
    )
    op.create_index(
        op.f("ix_rule_golden_test_artifacts_independent_review_id"),
        "rule_golden_test_artifacts",
        ["independent_review_id"],
    )
    op.create_index(
        "ix_rule_golden_test_artifacts_rule_type_rule_id",
        "rule_golden_test_artifacts",
        ["rule_type", "rule_id"],
    )
    for table_name, rule_type in RULE_TABLE_TYPES_WITH_GOLDEN_ARTIFACT:
        op.create_check_constraint(
            op.f(f"ck_{table_name}_golden_test_rule_type"),
            table_name,
            "(golden_test_ref IS NULL AND golden_test_rule_type IS NULL) OR "
            "(golden_test_ref IS NOT NULL AND golden_test_rule_type IS NOT NULL AND "
            f"golden_test_rule_type = '{rule_type}' AND "
            f"substr(golden_test_ref, 1, char_length('golden-run/{rule_type}/')) "
            f"= 'golden-run/{rule_type}/')",
        )
        op.create_foreign_key(
            op.f(f"fk_{table_name}_golden_test_ref_rule_golden_test_artifacts"),
            table_name,
            "rule_golden_test_artifacts",
            ["golden_test_ref", "id", "golden_test_rule_type"],
            ["artifact_ref", "rule_id", "rule_type"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    op.execute(
        "LOCK TABLE institutions, campuses, rule_golden_test_artifacts, "
        + ", ".join(table_name for table_name, _ in RULE_TABLE_TYPES_WITH_GOLDEN_ARTIFACT)
        + " IN ACCESS EXCLUSIVE MODE"
    )
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM rule_golden_test_artifacts) "
        "OR EXISTS (SELECT 1 FROM institutions WHERE code IS NOT NULL) "
        "OR EXISTS (SELECT 1 FROM campuses WHERE code IS NOT NULL) THEN "
        "RAISE EXCEPTION 'canonical code와 골든 테스트 증거를 보존한 채 내릴 수 없습니다.'; "
        "END IF; END $$"
    )
    for table_name, _rule_type in reversed(RULE_TABLE_TYPES_WITH_GOLDEN_ARTIFACT):
        op.drop_constraint(
            op.f(f"fk_{table_name}_golden_test_ref_rule_golden_test_artifacts"),
            table_name,
            type_="foreignkey",
        )
        op.drop_constraint(
            op.f(f"ck_{table_name}_golden_test_rule_type"),
            table_name,
            type_="check",
        )
        op.drop_column(table_name, "golden_test_rule_type")
    op.drop_table("rule_golden_test_artifacts")
    op.drop_constraint(
        op.f("uq_rule_reviews_id_rule_type_rule_id"),
        "rule_reviews",
        type_="unique",
    )
    op.drop_constraint(
        op.f("uq_campuses_institution_id_code"),
        "campuses",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_campuses_code_valid"),
        "campuses",
        type_="check",
    )
    op.drop_column("campuses", "code")
    op.drop_constraint(
        op.f("uq_institutions_code"),
        "institutions",
        type_="unique",
    )
    op.drop_constraint(
        op.f("ck_institutions_code_valid"),
        "institutions",
        type_="check",
    )
    op.drop_column("institutions", "code")
