"""Phase 16 teacher classrooms and explicit student account links."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8e31b7c4d2a6"
down_revision: str | None = "4a7c9e12d5f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "teacher_classrooms",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("teacher_user_account_id", sa.String(length=36), nullable=False),
        sa.Column("academic_year", sa.Integer(), nullable=False),
        sa.Column("department_name", sa.String(length=120), nullable=False),
        sa.Column("class_name", sa.String(length=80), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "academic_year BETWEEN 2000 AND 2100",
            name="academic_year_valid",
        ),
        sa.CheckConstraint(
            "department_name = btrim(department_name) "
            "AND char_length(department_name) BETWEEN 1 AND 120",
            name="department_name_valid",
        ),
        sa.CheckConstraint(
            "class_name = btrim(class_name) AND char_length(class_name) BETWEEN 1 AND 80",
            name="class_name_valid",
        ),
        sa.ForeignKeyConstraint(
            ["teacher_user_account_id"], ["user_accounts.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "teacher_user_account_id",
            "academic_year",
            "department_name",
            "class_name",
            name="uq_teacher_classrooms_owner_year_department_class",
        ),
    )
    op.create_index(
        op.f("ix_teacher_classrooms_teacher_user_account_id"),
        "teacher_classrooms",
        ["teacher_user_account_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_teacher_classrooms_academic_year"),
        "teacher_classrooms",
        ["academic_year"],
        unique=False,
    )

    op.create_table(
        "classroom_students",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("classroom_id", sa.String(length=36), nullable=False),
        sa.Column("anonymous_code", sa.String(length=40), nullable=False),
        sa.Column("linked_user_account_id", sa.String(length=36), nullable=True),
        sa.Column("link_code_digest", sa.String(length=64), nullable=True),
        sa.Column("link_code_hint", sa.String(length=4), nullable=True),
        sa.Column("link_code_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "anonymous_code = btrim(anonymous_code) "
            "AND char_length(anonymous_code) BETWEEN 1 AND 40",
            name="anonymous_code_valid",
        ),
        sa.CheckConstraint(
            "(linked_user_account_id IS NULL AND linked_at IS NULL "
            "AND link_code_digest IS NOT NULL AND char_length(link_code_digest) = 64 "
            "AND link_code_hint IS NOT NULL AND char_length(link_code_hint) = 4 "
            "AND link_code_expires_at IS NOT NULL) OR "
            "(linked_user_account_id IS NULL AND linked_at IS NULL "
            "AND link_code_digest IS NULL AND link_code_hint IS NULL "
            "AND link_code_expires_at IS NULL) OR "
            "(linked_user_account_id IS NOT NULL AND linked_at IS NOT NULL "
            "AND link_code_digest IS NULL AND link_code_hint IS NULL "
            "AND link_code_expires_at IS NULL)",
            name="link_state_consistent",
        ),
        sa.ForeignKeyConstraint(["classroom_id"], ["teacher_classrooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["linked_user_account_id"], ["user_accounts.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "classroom_id", "anonymous_code", name="uq_classroom_students_classroom_code"
        ),
        sa.UniqueConstraint(
            "classroom_id",
            "linked_user_account_id",
            name="uq_classroom_students_classroom_linked_user",
        ),
        sa.UniqueConstraint("link_code_digest", name="uq_classroom_students_link_code_digest"),
    )
    op.create_index(
        op.f("ix_classroom_students_classroom_id"),
        "classroom_students",
        ["classroom_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_classroom_students_linked_user_account_id"),
        "classroom_students",
        ["linked_user_account_id"],
        unique=False,
    )

    op.create_table(
        "classroom_link_audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("classroom_student_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_account_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "event_type IN ('ROSTER_STUDENT_CREATED', 'LINK_CODE_ROTATED', "
            "'LINK_CODE_REVOKED', 'STUDENT_LINKED', 'STUDENT_UNLINKED')",
            name="event_type_valid",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_account_id"], ["user_accounts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["classroom_student_id"], ["classroom_students.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_classroom_link_audit_events_classroom_student_id"),
        "classroom_link_audit_events",
        ["classroom_student_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_classroom_link_audit_events_actor_user_account_id"),
        "classroom_link_audit_events",
        ["actor_user_account_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_classroom_link_audit_events_actor_user_account_id"),
        table_name="classroom_link_audit_events",
    )
    op.drop_index(
        op.f("ix_classroom_link_audit_events_classroom_student_id"),
        table_name="classroom_link_audit_events",
    )
    op.drop_table("classroom_link_audit_events")
    op.drop_index(
        op.f("ix_classroom_students_linked_user_account_id"), table_name="classroom_students"
    )
    op.drop_index(op.f("ix_classroom_students_classroom_id"), table_name="classroom_students")
    op.drop_table("classroom_students")
    op.drop_index(op.f("ix_teacher_classrooms_academic_year"), table_name="teacher_classrooms")
    op.drop_index(
        op.f("ix_teacher_classrooms_teacher_user_account_id"),
        table_name="teacher_classrooms",
    )
    op.drop_table("teacher_classrooms")
