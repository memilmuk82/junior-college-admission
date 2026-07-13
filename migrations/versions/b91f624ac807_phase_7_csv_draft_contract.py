"""Phase 7 CSV DRAFT 저장 계약

Revision ID: b91f624ac807
Revises: a7d1e3b942c0
Create Date: 2026-07-13 11:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b91f624ac807"
down_revision: str | None = "a7d1e3b942c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = (
        sa.Column("admission_year", sa.Integer(), nullable=True),
        sa.Column("university_code", sa.String(length=80), nullable=True),
        sa.Column("university_name", sa.String(length=200), nullable=True),
        sa.Column("campus_code", sa.String(length=80), nullable=True),
        sa.Column("admission_round", sa.String(length=80), nullable=True),
        sa.Column("admission_track_code", sa.String(length=80), nullable=True),
        sa.Column("admission_track_name", sa.String(length=200), nullable=True),
        sa.Column("evidence_document_ref", sa.String(length=200), nullable=True),
        sa.Column("evidence_page", sa.Integer(), nullable=True),
        sa.Column("evidence_location", sa.String(length=240), nullable=True),
        sa.Column("source_status", sa.String(length=40), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("administrator_note", sa.Text(), nullable=True),
    )
    for column in columns:
        op.add_column("score_rules", column)
    op.create_index(op.f("ix_score_rules_admission_year"), "score_rules", ["admission_year"])
    op.create_check_constraint(
        op.f("ck_score_rules_business_key_complete"),
        "score_rules",
        "(admission_year IS NULL AND university_code IS NULL AND campus_code IS NULL "
        "AND admission_round IS NULL AND admission_track_code IS NULL) OR "
        "(admission_year IS NOT NULL AND university_code IS NOT NULL "
        "AND campus_code IS NOT NULL AND admission_round IS NOT NULL "
        "AND admission_track_code IS NOT NULL)",
    )
    op.create_unique_constraint(
        "business_key_version",
        "score_rules",
        [
            "admission_year",
            "university_code",
            "campus_code",
            "admission_round",
            "admission_track_code",
            "version",
        ],
    )
    op.create_index(
        "uq_score_rules_one_published_per_business_key",
        "score_rules",
        [
            "admission_year",
            "university_code",
            "campus_code",
            "admission_round",
            "admission_track_code",
        ],
        unique=True,
        postgresql_where=sa.text("lifecycle_status = 'PUBLISHED' AND admission_year IS NOT NULL"),
    )
    op.drop_constraint(
        op.f("ck_rule_audit_events_action_valid"),
        "rule_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_rule_audit_events_action_valid"),
        "rule_audit_events",
        "action IN ('DRAFT_CREATED', 'DRAFT_CLONED', 'HUMAN_APPROVED', "
        "'PUBLISHED', 'SUPERSEDED', 'REJECTED')",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_rule_audit_events_action_valid"),
        "rule_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_rule_audit_events_action_valid"),
        "rule_audit_events",
        "action IN ('DRAFT_CLONED', 'HUMAN_APPROVED', 'PUBLISHED', 'SUPERSEDED', 'REJECTED')",
    )
    op.drop_index("uq_score_rules_one_published_per_business_key", table_name="score_rules")
    op.drop_constraint("business_key_version", "score_rules", type_="unique")
    op.drop_constraint(op.f("ck_score_rules_business_key_complete"), "score_rules", type_="check")
    op.drop_index(op.f("ix_score_rules_admission_year"), table_name="score_rules")
    for column in (
        "administrator_note",
        "change_reason",
        "source_status",
        "evidence_location",
        "evidence_page",
        "evidence_document_ref",
        "admission_track_name",
        "admission_track_code",
        "admission_round",
        "campus_code",
        "university_name",
        "university_code",
        "admission_year",
    ):
        op.drop_column("score_rules", column)
