"""Phase 19 이메일 로그인과 계정 보안 저장 계약.

Revision ID: 3d9c0f7a21b4
Revises: b6f1e8a42c73
Create Date: 2026-07-20 14:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3d9c0f7a21b4"
down_revision: str | None = "b6f1e8a42c73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 이전 스키마는 login_name과 다른 행의 email 사이 교차 유일성을
    # 강제하지 않았다. 새 통합 식별자에서 모호해질 데이터는 추정 병합하지 않는다.
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1
                  FROM user_accounts AS login_account
                  JOIN user_accounts AS email_account
                    ON email_account.email = login_account.login_name
                   AND email_account.id <> login_account.id
            ) THEN
                RAISE EXCEPTION
                    '로그인 ID와 다른 계정 이메일의 교차 충돌을 먼저 해소해야 합니다.';
            END IF;
        END $$
        """
    )
    op.add_column(
        "user_accounts",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_accounts",
        sa.Column(
            "bootstrap_password_managed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    # Phase 11 Google 가입은 verified=true claim만 저장했으므로 그 계정만
    # 과거 외부 identity 생성 시각을 소유 확인 시각으로 안전하게 복원한다.
    op.execute(
        """
        UPDATE user_accounts AS account
           SET email_verified_at = identity.created_at
          FROM external_identities AS identity
         WHERE identity.user_account_id = account.id
           AND identity.provider = 'GOOGLE'
           AND account.email_verified_at IS NULL
        """
    )
    # 기존 환경변수 bootstrap 관리자만 계속 env hash 회전을 허용한다.
    # 사용자 생성 관리자와 공개 데모는 기본 false를 그대로 유지한다.
    op.execute(
        """
        UPDATE user_accounts
           SET bootstrap_password_managed = true
         WHERE role = 'ADMIN'
           AND actor_ref = login_name
           AND email LIKE 'bootstrap-%@local.invalid'
        """
    )

    op.drop_constraint(
        op.f("ck_user_accounts_local_credentials_complete"),
        "user_accounts",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_user_accounts_local_credentials_complete"),
        "user_accounts",
        "(login_name IS NULL OR "
        "(login_name = btrim(lower(login_name)) "
        "AND char_length(login_name) BETWEEN 4 AND 80)) "
        "AND (password_hash IS NULL OR char_length(password_hash) > 0) "
        "AND (login_name IS NULL OR password_hash IS NOT NULL)",
    )

    op.drop_constraint(
        op.f("ck_user_account_audit_events_event_type_valid"),
        "user_account_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_user_account_audit_events_event_type_valid"),
        "user_account_audit_events",
        "event_type IN ('REGISTERED_LOCAL', 'REGISTERED_GOOGLE', "
        "'BOOTSTRAPPED_ADMIN', 'APPROVED', 'ROLE_CHANGED', 'STATUS_CHANGED', "
        "'LOGIN_SUCCEEDED', 'PASSWORD_CHANGED', 'EMAIL_VERIFICATION_REQUESTED', "
        "'EMAIL_VERIFIED', 'EMAIL_CHANGED', 'PASSWORD_RESET_REQUESTED', "
        "'PASSWORD_RESET_COMPLETED', 'GOOGLE_LINKED', 'GOOGLE_UNLINKED')",
    )

    op.create_table(
        "account_auth_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_account_id", sa.String(length=36), nullable=False),
        sa.Column("purpose", sa.String(length=30), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column("issued_auth_version", sa.Integer(), nullable=False),
        sa.Column("target_email", sa.String(length=320), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
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
            "purpose IN ('EMAIL_VERIFICATION', 'PASSWORD_RESET')",
            name=op.f("ck_account_auth_tokens_purpose_valid"),
        ),
        sa.CheckConstraint(
            "token_digest ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_account_auth_tokens_token_digest_valid"),
        ),
        sa.CheckConstraint(
            "issued_auth_version > 0",
            name=op.f("ck_account_auth_tokens_issued_auth_version_positive"),
        ),
        sa.CheckConstraint(
            "target_email = btrim(lower(target_email)) "
            "AND char_length(target_email) BETWEEN 3 AND 320",
            name=op.f("ck_account_auth_tokens_target_email_normalized"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_account_auth_tokens_expiry_after_creation"),
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR consumed_at >= created_at",
            name=op.f("ck_account_auth_tokens_consumed_after_creation"),
        ),
        sa.CheckConstraint(
            "revoked_at IS NULL OR revoked_at >= created_at",
            name=op.f("ck_account_auth_tokens_revoked_after_creation"),
        ),
        sa.CheckConstraint(
            "consumed_at IS NULL OR revoked_at IS NULL",
            name=op.f("ck_account_auth_tokens_single_terminal_state"),
        ),
        sa.ForeignKeyConstraint(
            ["user_account_id"],
            ["user_accounts.id"],
            name=op.f("fk_account_auth_tokens_user_account_id_user_accounts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_auth_tokens")),
        sa.UniqueConstraint(
            "token_digest",
            name=op.f("uq_account_auth_tokens_token_digest"),
        ),
    )
    op.create_index(
        op.f("ix_account_auth_tokens_user_account_id"),
        "account_auth_tokens",
        ["user_account_id"],
    )
    op.create_index(
        "ix_account_auth_tokens_user_purpose_created",
        "account_auth_tokens",
        ["user_account_id", "purpose", "created_at"],
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute(
        "LOCK TABLE user_accounts, external_identities, user_account_audit_events, "
        "account_auth_tokens IN ACCESS EXCLUSIVE MODE"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM account_auth_tokens) THEN
                RAISE EXCEPTION
                    '계정 인증 token을 보존한 채 Phase 19 migration을 내릴 수 없습니다.';
            END IF;
            IF EXISTS (
                SELECT 1
                  FROM user_accounts
                 WHERE role = 'ADMIN'
                   AND actor_ref = login_name
                   AND email LIKE 'bootstrap-%@local.invalid'
                   AND bootstrap_password_managed = false
            ) THEN
                RAISE EXCEPTION
                    '사용자가 변경한 bootstrap 비밀번호를 보존한 채 Phase 19 migration을 내릴 수 없습니다.';
            END IF;
            IF EXISTS (
                SELECT 1 FROM user_accounts
                 WHERE (login_name IS NULL) <> (password_hash IS NULL)
            ) THEN
                RAISE EXCEPTION
                    'email-only 로컬 계정을 보존한 채 Phase 19 migration을 내릴 수 없습니다.';
            END IF;
            IF EXISTS (
                SELECT 1
                  FROM user_accounts AS account
                 WHERE account.email_verified_at IS NOT NULL
                   AND NOT (
                       account.password_hash IS NULL
                       AND EXISTS (
                           SELECT 1
                             FROM external_identities AS identity
                            WHERE identity.user_account_id = account.id
                              AND identity.provider = 'GOOGLE'
                       )
                   )
            ) THEN
                RAISE EXCEPTION
                    '이메일 검증 상태를 보존한 채 Phase 19 migration을 내릴 수 없습니다.';
            END IF;
            IF EXISTS (
                SELECT 1 FROM user_account_audit_events
                 WHERE event_type IN (
                    'EMAIL_VERIFICATION_REQUESTED', 'EMAIL_VERIFIED', 'EMAIL_CHANGED',
                    'PASSWORD_RESET_REQUESTED', 'PASSWORD_RESET_COMPLETED',
                    'GOOGLE_LINKED', 'GOOGLE_UNLINKED'
                 )
            ) THEN
                RAISE EXCEPTION
                    '계정 보안 감사 기록을 보존한 채 Phase 19 migration을 내릴 수 없습니다.';
            END IF;
        END $$
        """
    )

    op.drop_index(
        "ix_account_auth_tokens_user_purpose_created",
        table_name="account_auth_tokens",
    )
    op.drop_index(
        op.f("ix_account_auth_tokens_user_account_id"),
        table_name="account_auth_tokens",
    )
    op.drop_table("account_auth_tokens")

    op.drop_constraint(
        op.f("ck_user_account_audit_events_event_type_valid"),
        "user_account_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_user_account_audit_events_event_type_valid"),
        "user_account_audit_events",
        "event_type IN ('REGISTERED_LOCAL', 'REGISTERED_GOOGLE', "
        "'BOOTSTRAPPED_ADMIN', 'APPROVED', 'ROLE_CHANGED', 'STATUS_CHANGED', "
        "'LOGIN_SUCCEEDED', 'PASSWORD_CHANGED')",
    )

    op.drop_constraint(
        op.f("ck_user_accounts_local_credentials_complete"),
        "user_accounts",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_user_accounts_local_credentials_complete"),
        "user_accounts",
        "(login_name IS NULL AND password_hash IS NULL) OR "
        "(login_name IS NOT NULL AND password_hash IS NOT NULL AND "
        "login_name = btrim(lower(login_name)) "
        "AND char_length(login_name) BETWEEN 4 AND 80 "
        "AND char_length(password_hash) > 0)",
    )
    op.drop_column("user_accounts", "bootstrap_password_managed")
    op.drop_column("user_accounts", "email_verified_at")
