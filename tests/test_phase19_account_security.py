from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app.models import AccountAuthToken, ExternalIdentity, UserAccount, UserAccountAuditEvent
from app.services.account_security import (
    account_token_is_usable,
    change_password,
    connect_google_identity,
    disconnect_google_identity,
    issue_email_verification_token,
    issue_password_reset_token,
    reset_password_with_token,
    verify_email_token,
)
from app.services.membership import (
    MembershipError,
    approve_pending_member,
    authenticate_local_member,
    bootstrap_admin,
    change_member_status,
    register_local_member,
)


@pytest.fixture(autouse=True)
def clean_phase19_accounts(postgres_engine: Engine) -> Iterator[None]:
    yield
    with postgres_engine.begin() as connection:
        account_filter = (
            "SELECT id FROM user_accounts WHERE email LIKE '%@phase19.invalid' "
            "OR login_name LIKE 'phase19-%'"
        )
        connection.execute(
            text(
                "DELETE FROM user_account_audit_events WHERE target_user_id IN "
                f"({account_filter}) OR actor_user_id IN ({account_filter})"
            )
        )
        connection.execute(
            text(f"DELETE FROM external_identities WHERE user_account_id IN ({account_filter})")
        )
        connection.execute(
            text(f"DELETE FROM account_auth_tokens WHERE user_account_id IN ({account_filter})")
        )
        connection.execute(
            text(
                "DELETE FROM user_accounts WHERE email LIKE '%@phase19.invalid' "
                "OR login_name LIKE 'phase19-%'"
            )
        )


def _admin(database_session: Session, *, at: datetime) -> UserAccount:
    return bootstrap_admin(
        database_session,
        login_name="phase19-admin",
        password_hash=generate_password_hash("phase19-admin-password"),
        occurred_at=at,
    )


def test_email_only_registration_requires_one_time_verification_before_login_and_approval(
    postgres_engine: Engine,
) -> None:
    registered_at = datetime(2026, 7, 20, 13, 0, tzinfo=UTC)
    with Session(postgres_engine) as database_session:
        admin = _admin(database_session, at=registered_at)
        member = register_local_member(
            database_session,
            login_name=None,
            email="  New.Student@phase19.invalid ",
            display_name="합성 신규 학생",
            password="phase19-student-password",
            requested_role="STUDENT",
            occurred_at=registered_at + timedelta(minutes=1),
        )
        database_session.flush()

        assert member.login_name is None
        assert member.email == "new.student@phase19.invalid"
        assert member.email_verified_at is None
        assert (
            authenticate_local_member(
                database_session,
                login_name="new.student@phase19.invalid",
                password="phase19-student-password",
                occurred_at=registered_at + timedelta(minutes=2),
            )
            is None
        )
        with pytest.raises(MembershipError, match="이메일"):
            approve_pending_member(
                database_session,
                actor=admin,
                target=member,
                occurred_at=registered_at + timedelta(minutes=3),
            )

        raw_token = issue_email_verification_token(
            database_session,
            user=member,
            target_email=member.email,
            occurred_at=registered_at + timedelta(minutes=4),
        )
        database_session.flush()
        stored_token = database_session.scalar(
            select(AccountAuthToken).where(AccountAuthToken.user_account_id == member.id)
        )
        assert stored_token is not None
        assert stored_token.token_digest != raw_token
        assert raw_token not in repr(stored_token.__dict__)

        verified = verify_email_token(
            database_session,
            raw_token=raw_token,
            occurred_at=registered_at + timedelta(minutes=5),
        )
        assert verified.id == member.id
        assert verified.email_verified_at == registered_at + timedelta(minutes=5)
        assert stored_token.consumed_at == registered_at + timedelta(minutes=5)
        with pytest.raises(MembershipError, match="유효하지|사용|만료"):
            verify_email_token(
                database_session,
                raw_token=raw_token,
                occurred_at=registered_at + timedelta(minutes=6),
            )

        approve_pending_member(
            database_session,
            actor=admin,
            target=member,
            occurred_at=registered_at + timedelta(minutes=7),
        )
        authenticated = authenticate_local_member(
            database_session,
            login_name="NEW.STUDENT@phase19.invalid",
            password="phase19-student-password",
            occurred_at=registered_at + timedelta(minutes=8),
        )
        assert authenticated is not None
        assert authenticated.id == member.id


def test_password_change_rotates_auth_version_and_stops_bootstrap_password_management(
    postgres_engine: Engine,
) -> None:
    changed_at = datetime(2026, 7, 20, 14, 0, tzinfo=UTC)
    with Session(postgres_engine) as database_session:
        admin = _admin(database_session, at=changed_at - timedelta(minutes=1))
        original_version = admin.auth_version
        assert admin.bootstrap_password_managed is True
        pending_email_token = issue_email_verification_token(
            database_session,
            user=admin,
            target_email="phase19-admin-new@phase19.invalid",
            occurred_at=changed_at - timedelta(seconds=30),
        )

        changed = change_password(
            database_session,
            user=admin,
            current_password="phase19-admin-password",
            new_password="phase19-user-selected-password",
            occurred_at=changed_at,
        )
        assert changed.id == admin.id
        assert changed.auth_version == original_version + 1
        assert changed.bootstrap_password_managed is False
        with pytest.raises(MembershipError, match="유효하지|만료"):
            verify_email_token(
                database_session,
                raw_token=pending_email_token,
                occurred_at=changed_at + timedelta(seconds=30),
            )
        assert (
            authenticate_local_member(
                database_session,
                login_name="phase19-admin",
                password="phase19-admin-password",
                occurred_at=changed_at + timedelta(minutes=1),
            )
            is None
        )
        assert (
            authenticate_local_member(
                database_session,
                login_name="phase19-admin",
                password="phase19-user-selected-password",
                occurred_at=changed_at + timedelta(minutes=2),
            )
            is not None
        )
        bootstrap_admin(
            database_session,
            login_name="phase19-admin",
            password_hash=generate_password_hash("phase19-admin-password"),
            occurred_at=changed_at + timedelta(minutes=3),
        )
        assert (
            authenticate_local_member(
                database_session,
                login_name="phase19-admin",
                password="phase19-user-selected-password",
                occurred_at=changed_at + timedelta(minutes=4),
            )
            is not None
        )

        event_types = set(
            database_session.scalars(
                select(UserAccountAuditEvent.event_type).where(
                    UserAccountAuditEvent.target_user_id == admin.id
                )
            )
        )
        assert "PASSWORD_CHANGED" in event_types


def test_legacy_login_id_containing_at_sign_remains_usable_without_email_verification(
    postgres_engine: Engine,
) -> None:
    occurred_at = datetime(2026, 7, 20, 14, 30, tzinfo=UTC)
    with Session(postgres_engine) as database_session:
        member = register_local_member(
            database_session,
            login_name="legacy-id@phase19.invalid",
            email="legacy-placeholder@phase19.invalid",
            display_name="합성 기존 이메일형 아이디",
            password="phase19-legacy-password",
            occurred_at=occurred_at,
        )
        database_session.flush()

        assert member.email_verified_at is None
        authenticated = authenticate_local_member(
            database_session,
            login_name="LEGACY-ID@phase19.invalid",
            password="phase19-legacy-password",
            occurred_at=occurred_at + timedelta(minutes=1),
        )
        assert authenticated is not None
        assert authenticated.id == member.id


def test_password_reset_token_is_generic_single_use_and_invalidates_old_password(
    postgres_engine: Engine,
) -> None:
    issued_at = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)
    with Session(postgres_engine) as database_session:
        member = register_local_member(
            database_session,
            login_name="phase19-reset-member",
            email="reset@phase19.invalid",
            display_name="합성 재설정 회원",
            password="phase19-original-password",
            occurred_at=issued_at - timedelta(minutes=1),
        )
        member.email_verified_at = issued_at - timedelta(seconds=30)
        database_session.flush()
        original_version = member.auth_version
        pending_email_token = issue_email_verification_token(
            database_session,
            user=member,
            target_email="reset-new@phase19.invalid",
            occurred_at=issued_at - timedelta(seconds=15),
        )

        assert (
            issue_password_reset_token(
                database_session,
                email="missing@phase19.invalid",
                occurred_at=issued_at,
            )
            is None
        )
        issued = issue_password_reset_token(
            database_session,
            email=" RESET@phase19.invalid ",
            occurred_at=issued_at,
        )
        assert issued is not None
        issued_member, raw_token = issued
        assert issued_member.id == member.id

        reset = reset_password_with_token(
            database_session,
            raw_token=raw_token,
            new_password="phase19-replacement-password",
            occurred_at=issued_at + timedelta(minutes=1),
        )
        assert reset.auth_version == original_version + 1
        with pytest.raises(MembershipError, match="유효하지|만료"):
            verify_email_token(
                database_session,
                raw_token=pending_email_token,
                occurred_at=issued_at + timedelta(minutes=1, seconds=30),
            )
        with pytest.raises(MembershipError, match="유효하지|사용|만료"):
            reset_password_with_token(
                database_session,
                raw_token=raw_token,
                new_password="phase19-another-password",
                occurred_at=issued_at + timedelta(minutes=2),
            )
        assert (
            authenticate_local_member(
                database_session,
                login_name="phase19-reset-member",
                password="phase19-original-password",
                occurred_at=issued_at + timedelta(minutes=3),
            )
            is None
        )
        assert (
            authenticate_local_member(
                database_session,
                login_name="reset@phase19.invalid",
                password="phase19-replacement-password",
                occurred_at=issued_at + timedelta(minutes=4),
            )
            is not None
        )


def test_admin_status_change_invalidates_previously_issued_account_token(
    postgres_engine: Engine,
) -> None:
    issued_at = datetime(2026, 7, 20, 15, 30, tzinfo=UTC)
    with Session(postgres_engine) as database_session:
        admin = _admin(database_session, at=issued_at - timedelta(minutes=3))
        member = register_local_member(
            database_session,
            login_name="phase19-suspended-member",
            email="suspended@phase19.invalid",
            display_name="합성 정지 회원",
            password="phase19-suspended-password",
            occurred_at=issued_at - timedelta(minutes=2),
        )
        member.email_verified_at = issued_at - timedelta(minutes=1)
        approve_pending_member(
            database_session,
            actor=admin,
            target=member,
            occurred_at=issued_at - timedelta(seconds=30),
        )
        issued = issue_password_reset_token(
            database_session,
            email=member.email,
            occurred_at=issued_at,
        )
        assert issued is not None
        _, raw_token = issued
        change_member_status(
            database_session,
            actor=admin,
            target=member,
            new_status="SUSPENDED",
            occurred_at=issued_at + timedelta(minutes=1),
        )

        assert not account_token_is_usable(
            database_session,
            raw_token=raw_token,
            purpose="PASSWORD_RESET",
            occurred_at=issued_at + timedelta(minutes=2),
        )
        with pytest.raises(MembershipError, match="유효하지|만료"):
            reset_password_with_token(
                database_session,
                raw_token=raw_token,
                new_password="phase19-after-suspension-password",
                occurred_at=issued_at + timedelta(minutes=2),
            )


def test_google_identity_requires_explicit_matching_email_link_and_safe_unlink(
    postgres_engine: Engine,
) -> None:
    linked_at = datetime(2026, 7, 20, 16, 0, tzinfo=UTC)
    with Session(postgres_engine) as database_session:
        admin = _admin(database_session, at=linked_at - timedelta(minutes=3))
        member = register_local_member(
            database_session,
            login_name="phase19-google-member",
            email="google-link@phase19.invalid",
            display_name="합성 Google 연결 회원",
            password="phase19-google-password",
            occurred_at=linked_at - timedelta(minutes=1),
        )
        member.email_verified_at = linked_at - timedelta(seconds=30)
        approve_pending_member(
            database_session,
            actor=admin,
            target=member,
            occurred_at=linked_at - timedelta(seconds=15),
        )
        database_session.flush()

        with pytest.raises(MembershipError, match="이메일"):
            connect_google_identity(
                database_session,
                user=member,
                issuer="https://accounts.google.com",
                subject="phase19-wrong-email-subject",
                email="different@phase19.invalid",
                email_verified=True,
                occurred_at=linked_at,
            )

        identity = connect_google_identity(
            database_session,
            user=member,
            issuer="https://accounts.google.com",
            subject="phase19-google-subject",
            email="GOOGLE-LINK@phase19.invalid",
            email_verified=True,
            occurred_at=linked_at + timedelta(minutes=1),
        )
        assert identity.user_account_id == member.id
        assert identity.provider_subject == "phase19-google-subject"
        assert (
            database_session.scalar(
                select(ExternalIdentity).where(ExternalIdentity.user_account_id == member.id)
            )
            is not None
        )

        with pytest.raises(MembershipError, match="비밀번호"):
            disconnect_google_identity(
                database_session,
                user=member,
                current_password="wrong-password",
                occurred_at=linked_at + timedelta(minutes=2),
            )
        disconnect_google_identity(
            database_session,
            user=member,
            current_password="phase19-google-password",
            occurred_at=linked_at + timedelta(minutes=3),
        )
        assert (
            database_session.scalar(
                select(ExternalIdentity).where(ExternalIdentity.user_account_id == member.id)
            )
            is None
        )
