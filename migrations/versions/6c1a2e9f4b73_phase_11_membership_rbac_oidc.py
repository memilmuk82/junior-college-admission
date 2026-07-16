"""Phase 11 회원 승인·권한·OIDC 저장 계약

Revision ID: 6c1a2e9f4b73
Revises: 0d9f4a7c2b11
Create Date: 2026-07-15 08:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6c1a2e9f4b73"
down_revision: str | None = "0d9f4a7c2b11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("actor_ref", sa.String(length=120), nullable=False),
        sa.Column("login_name", sa.String(length=80), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("approved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
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
            "role IN ('ADMIN', 'ASSISTANT_ADMIN', 'MEMBER')",
            name=op.f("ck_user_accounts_role_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING_APPROVAL', 'ACTIVE', 'REJECTED', 'SUSPENDED')",
            name=op.f("ck_user_accounts_status_valid"),
        ),
        sa.CheckConstraint(
            "auth_version > 0",
            name=op.f("ck_user_accounts_auth_version_positive"),
        ),
        sa.CheckConstraint(
            "email = btrim(lower(email)) AND char_length(email) BETWEEN 3 AND 320",
            name=op.f("ck_user_accounts_email_normalized"),
        ),
        sa.CheckConstraint(
            "display_name = btrim(display_name) AND char_length(display_name) BETWEEN 1 AND 120",
            name=op.f("ck_user_accounts_display_name_valid"),
        ),
        sa.CheckConstraint(
            "actor_ref = btrim(actor_ref) AND char_length(actor_ref) BETWEEN 1 AND 120",
            name=op.f("ck_user_accounts_actor_ref_valid"),
        ),
        sa.CheckConstraint(
            "(login_name IS NULL AND password_hash IS NULL) OR "
            "(login_name IS NOT NULL AND password_hash IS NOT NULL AND "
            "login_name = btrim(lower(login_name)) AND char_length(login_name) BETWEEN 4 AND 80 "
            "AND char_length(password_hash) > 0)",
            name=op.f("ck_user_accounts_local_credentials_complete"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('PENDING_APPROVAL', 'REJECTED') OR role = 'MEMBER'",
            name=op.f("ck_user_accounts_pending_role_member"),
        ),
        sa.CheckConstraint(
            "(status IN ('PENDING_APPROVAL', 'REJECTED') AND approved_at IS NULL "
            "AND approved_by_user_id IS NULL) OR "
            "(status IN ('ACTIVE', 'SUSPENDED') AND approved_at IS NOT NULL "
            "AND approved_by_user_id IS NOT NULL)",
            name=op.f("ck_user_accounts_approval_state_consistent"),
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["user_accounts.id"],
            name=op.f("fk_user_accounts_approved_by_user_id_user_accounts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_accounts")),
        sa.UniqueConstraint("email", name=op.f("uq_user_accounts_email")),
        sa.UniqueConstraint("login_name", name=op.f("uq_user_accounts_login_name")),
        sa.UniqueConstraint("actor_ref", name=op.f("uq_user_accounts_actor_ref")),
    )
    op.create_index(
        op.f("ix_user_accounts_approved_by_user_id"),
        "user_accounts",
        ["approved_by_user_id"],
    )
    op.create_index(op.f("ix_user_accounts_status"), "user_accounts", ["status"])
    op.create_index(
        "ix_user_accounts_status_role",
        "user_accounts",
        ["status", "role"],
    )

    op.create_table(
        "external_identities",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_account_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("issuer", sa.String(length=200), nullable=False),
        sa.Column("provider_subject", sa.String(length=255), nullable=False),
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
            "provider = 'GOOGLE'",
            name=op.f("ck_external_identities_provider_valid"),
        ),
        sa.CheckConstraint(
            "issuer = 'https://accounts.google.com'",
            name=op.f("ck_external_identities_issuer_valid"),
        ),
        sa.CheckConstraint(
            "provider_subject = btrim(provider_subject) "
            "AND char_length(provider_subject) BETWEEN 1 AND 255",
            name=op.f("ck_external_identities_provider_subject_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_account_id"],
            ["user_accounts.id"],
            name=op.f("fk_external_identities_user_account_id_user_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_identities")),
        sa.UniqueConstraint(
            "provider",
            "issuer",
            "provider_subject",
            name=op.f("uq_external_identities_provider"),
        ),
        sa.UniqueConstraint(
            "user_account_id",
            "provider",
            name=op.f("uq_external_identities_user_account_id"),
        ),
    )
    op.create_index(
        op.f("ix_external_identities_user_account_id"),
        "external_identities",
        ["user_account_id"],
    )

    op.create_table(
        "user_account_audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("target_user_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("before_role", sa.String(length=30), nullable=True),
        sa.Column("after_role", sa.String(length=30), nullable=True),
        sa.Column("before_status", sa.String(length=30), nullable=True),
        sa.Column("after_status", sa.String(length=30), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
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
            "event_type IN ('REGISTERED_LOCAL', 'REGISTERED_GOOGLE', "
            "'BOOTSTRAPPED_ADMIN', 'APPROVED', 'ROLE_CHANGED', 'STATUS_CHANGED', "
            "'LOGIN_SUCCEEDED', 'PASSWORD_CHANGED')",
            name=op.f("ck_user_account_audit_events_event_type_valid"),
        ),
        sa.CheckConstraint(
            "before_role IS NULL OR before_role IN ('ADMIN', 'ASSISTANT_ADMIN', 'MEMBER')",
            name=op.f("ck_user_account_audit_events_before_role_valid"),
        ),
        sa.CheckConstraint(
            "after_role IS NULL OR after_role IN ('ADMIN', 'ASSISTANT_ADMIN', 'MEMBER')",
            name=op.f("ck_user_account_audit_events_after_role_valid"),
        ),
        sa.CheckConstraint(
            "before_status IS NULL OR before_status IN "
            "('PENDING_APPROVAL', 'ACTIVE', 'REJECTED', 'SUSPENDED')",
            name=op.f("ck_user_account_audit_events_before_status_valid"),
        ),
        sa.CheckConstraint(
            "after_status IS NULL OR after_status IN "
            "('PENDING_APPROVAL', 'ACTIVE', 'REJECTED', 'SUSPENDED')",
            name=op.f("ck_user_account_audit_events_after_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["user_accounts.id"],
            name=op.f("fk_user_account_audit_events_actor_user_id_user_accounts"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["user_accounts.id"],
            name=op.f("fk_user_account_audit_events_target_user_id_user_accounts"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_account_audit_events")),
    )
    op.create_index(
        op.f("ix_user_account_audit_events_actor_user_id"),
        "user_account_audit_events",
        ["actor_user_id"],
    )
    op.create_index(
        op.f("ix_user_account_audit_events_target_user_id"),
        "user_account_audit_events",
        ["target_user_id"],
    )
    op.create_index(
        "ix_user_account_audit_events_target_occurred",
        "user_account_audit_events",
        ["target_user_id", "occurred_at"],
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "LOCK TABLE user_accounts, external_identities, user_account_audit_events "
        "IN ACCESS EXCLUSIVE MODE"
    )
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM user_accounts) "
        "OR EXISTS (SELECT 1 FROM external_identities) "
        "OR EXISTS (SELECT 1 FROM user_account_audit_events) THEN "
        "RAISE EXCEPTION '회원 계정, 외부 로그인 또는 감사 기록을 보존한 채 "
        "membership migration을 내릴 수 없습니다.'; "
        "END IF; END $$"
    )
    op.drop_index(
        "ix_user_account_audit_events_target_occurred",
        table_name="user_account_audit_events",
    )
    op.drop_index(
        op.f("ix_user_account_audit_events_target_user_id"),
        table_name="user_account_audit_events",
    )
    op.drop_index(
        op.f("ix_user_account_audit_events_actor_user_id"),
        table_name="user_account_audit_events",
    )
    op.drop_table("user_account_audit_events")
    op.drop_index(
        op.f("ix_external_identities_user_account_id"),
        table_name="external_identities",
    )
    op.drop_table("external_identities")
    op.drop_index("ix_user_accounts_status_role", table_name="user_accounts")
    op.drop_index(op.f("ix_user_accounts_status"), table_name="user_accounts")
    op.drop_index(
        op.f("ix_user_accounts_approved_by_user_id"),
        table_name="user_accounts",
    )
    op.drop_table("user_accounts")
