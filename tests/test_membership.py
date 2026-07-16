from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import ExternalIdentity, UserAccount, UserAccountAuditEvent
from app.services.membership import (
    MembershipError,
    approve_pending_member,
    bootstrap_admin,
    change_member_role,
    change_member_status,
    register_google_member,
    register_local_member,
)


@pytest.fixture
def membership_session(postgres_engine: Engine) -> Iterator[Session]:
    connection = postgres_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def _active_admin(session: Session, login_name: str = "synthetic-admin") -> UserAccount:
    return bootstrap_admin(
        session,
        login_name=login_name,
        password_hash=generate_password_hash("synthetic-admin-password"),
        occurred_at=datetime(2026, 7, 15, 9, 0, tzinfo=UTC),
    )


def test_local_registration_forces_pending_member_and_hashes_password(
    membership_session: Session,
) -> None:
    member = register_local_member(
        membership_session,
        login_name="  SYNTHETIC.Teacher  ",
        email="  Teacher@Example.invalid ",
        display_name="  합성 교사  ",
        password="synthetic-member-password",
        requested_role="ADMIN",
        requested_status="ACTIVE",
        occurred_at=datetime(2026, 7, 15, 9, 1, tzinfo=UTC),
    )
    membership_session.flush()

    assert member.login_name == "synthetic.teacher"
    assert member.actor_ref == f"user:{member.id}"
    assert member.email == "teacher@example.invalid"
    assert member.display_name == "합성 교사"
    assert member.role == "MEMBER"
    assert member.status == "PENDING_APPROVAL"
    assert member.approved_at is None
    assert member.approved_by_user_id is None
    assert member.password_hash is not None
    assert member.password_hash != "synthetic-member-password"
    assert check_password_hash(member.password_hash, "synthetic-member-password")
    assert (
        membership_session.query(UserAccountAuditEvent)
        .filter_by(target_user_id=member.id, event_type="REGISTERED_LOCAL")
        .one()
    )


def test_assistant_admin_can_only_approve_pending_member(membership_session: Session) -> None:
    admin = _active_admin(membership_session)
    assistant = register_local_member(
        membership_session,
        login_name="synthetic-assistant",
        email="assistant@example.invalid",
        display_name="합성 보조 관리자",
        password="synthetic-assistant-password",
        occurred_at=datetime(2026, 7, 15, 9, 2, tzinfo=UTC),
    )
    approve_pending_member(
        membership_session,
        actor=admin,
        target=assistant,
        occurred_at=datetime(2026, 7, 15, 9, 3, tzinfo=UTC),
    )
    change_member_role(
        membership_session,
        actor=admin,
        target=assistant,
        new_role="ASSISTANT_ADMIN",
        occurred_at=datetime(2026, 7, 15, 9, 4, tzinfo=UTC),
    )
    member = register_local_member(
        membership_session,
        login_name="synthetic-member",
        email="member@example.invalid",
        display_name="합성 회원",
        password="synthetic-member-password",
        occurred_at=datetime(2026, 7, 15, 9, 5, tzinfo=UTC),
    )

    approve_pending_member(
        membership_session,
        actor=assistant,
        target=member,
        occurred_at=datetime(2026, 7, 15, 9, 6, tzinfo=UTC),
    )
    assert member.status == "ACTIVE"
    assert member.approved_by_user_id == assistant.id
    assert member.auth_version == 2

    with pytest.raises(MembershipError, match="역할"):
        change_member_role(
            membership_session,
            actor=assistant,
            target=member,
            new_role="ADMIN",
            occurred_at=datetime(2026, 7, 15, 9, 7, tzinfo=UTC),
        )


def test_last_active_admin_cannot_be_demoted(membership_session: Session) -> None:
    admin = _active_admin(membership_session)

    with pytest.raises(MembershipError, match="마지막 활성 관리자"):
        change_member_role(
            membership_session,
            actor=admin,
            target=admin,
            new_role="MEMBER",
            occurred_at=datetime(2026, 7, 15, 9, 8, tzinfo=UTC),
        )


def test_bootstrap_admin_is_idempotent_and_never_silently_elevates_pending_user(
    membership_session: Session,
) -> None:
    first = _active_admin(membership_session)
    second = _active_admin(membership_session)

    assert second.id == first.id
    assert second.actor_ref == "synthetic-admin"
    assert second.role == "ADMIN"
    assert second.status == "ACTIVE"

    register_local_member(
        membership_session,
        login_name="collision",
        email="collision@example.invalid",
        display_name="합성 충돌 회원",
        password="synthetic-member-password",
        occurred_at=datetime(2026, 7, 15, 9, 9, tzinfo=UTC),
    )
    with pytest.raises(MembershipError, match="기존 회원"):
        bootstrap_admin(
            membership_session,
            login_name="collision",
            password_hash=generate_password_hash("synthetic-admin-password"),
            occurred_at=datetime(2026, 7, 15, 9, 10, tzinfo=UTC),
        )


def test_concurrent_bootstrap_admin_creates_one_account(postgres_engine: Engine) -> None:
    login_name = "phase11-concurrent-bootstrap"
    password_hash = generate_password_hash("synthetic-admin-password")

    def cleanup() -> None:
        with postgres_engine.begin() as connection:
            account_ids = f"SELECT id FROM user_accounts WHERE login_name = '{login_name}'"
            connection.execute(
                text(
                    "DELETE FROM user_account_audit_events WHERE target_user_id IN "
                    f"({account_ids}) OR actor_user_id IN ({account_ids})"
                )
            )
            connection.execute(text(f"DELETE FROM user_accounts WHERE login_name = '{login_name}'"))

    cleanup()
    start = Barrier(2)

    def run_bootstrap() -> str:
        with Session(postgres_engine) as database_session:
            start.wait(timeout=5)
            admin = bootstrap_admin(
                database_session,
                login_name=login_name,
                password_hash=password_hash,
                occurred_at=datetime(2026, 7, 15, 9, 10, tzinfo=UTC),
            )
            database_session.commit()
            return admin.id

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run_bootstrap) for _ in range(2)]
            account_ids = [future.result(timeout=10) for future in futures]

        assert account_ids[0] == account_ids[1]
        with Session(postgres_engine) as verification_session:
            accounts = tuple(
                verification_session.scalars(
                    select(UserAccount).where(UserAccount.login_name == login_name)
                )
            )
            assert len(accounts) == 1
            assert (accounts[0].role, accounts[0].status) == ("ADMIN", "ACTIVE")
    finally:
        cleanup()


def test_google_registration_uses_issuer_subject_and_never_auto_links_email(
    membership_session: Session,
) -> None:
    google_member = register_google_member(
        membership_session,
        issuer="https://accounts.google.com",
        subject="synthetic-google-subject-1",
        email="google-user@example.invalid",
        email_verified=True,
        display_name="합성 Google 회원",
        occurred_at=datetime(2026, 7, 15, 9, 11, tzinfo=UTC),
    )
    same_member = register_google_member(
        membership_session,
        issuer="accounts.google.com",
        subject="synthetic-google-subject-1",
        email="changed@example.invalid",
        email_verified=True,
        display_name="변경 표시명",
        occurred_at=datetime(2026, 7, 15, 9, 12, tzinfo=UTC),
    )

    assert same_member.id == google_member.id
    assert google_member.actor_ref == f"user:{google_member.id}"
    assert google_member.role == "MEMBER"
    assert google_member.status == "PENDING_APPROVAL"
    identity = (
        membership_session.query(ExternalIdentity)
        .filter_by(provider="GOOGLE", provider_subject="synthetic-google-subject-1")
        .one()
    )
    assert identity.user_account_id == google_member.id
    assert identity.issuer == "https://accounts.google.com"

    register_local_member(
        membership_session,
        login_name="local-same-email",
        email="occupied@example.invalid",
        display_name="합성 로컬 회원",
        password="synthetic-member-password",
        occurred_at=datetime(2026, 7, 15, 9, 13, tzinfo=UTC),
    )
    with pytest.raises(MembershipError, match="자동 연결"):
        register_google_member(
            membership_session,
            issuer="https://accounts.google.com",
            subject="synthetic-google-subject-2",
            email="occupied@example.invalid",
            email_verified=True,
            display_name="합성 Google 충돌",
            occurred_at=datetime(2026, 7, 15, 9, 14, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("issuer", "subject", "email", "email_verified"),
    [
        ("https://untrusted.example.invalid", "subject", "user@example.invalid", True),
        ("https://accounts.google.com", "", "user@example.invalid", True),
        ("https://accounts.google.com", "subject", "user@example.invalid", False),
    ],
)
def test_google_registration_rejects_unverified_or_invalid_claims(
    membership_session: Session,
    issuer: str,
    subject: str,
    email: str,
    email_verified: bool,
) -> None:
    with pytest.raises(MembershipError):
        register_google_member(
            membership_session,
            issuer=issuer,
            subject=subject,
            email=email,
            email_verified=email_verified,
            display_name="합성 Google 회원",
            occurred_at=datetime(2026, 7, 15, 9, 15, tzinfo=UTC),
        )


def test_approval_reloads_locked_actor_after_concurrent_demotion(
    postgres_engine: Engine,
) -> None:
    login_prefix = "phase11-stale-actor-"

    def cleanup() -> None:
        with postgres_engine.begin() as connection:
            account_ids = f"SELECT id FROM user_accounts WHERE login_name LIKE '{login_prefix}%'"
            connection.execute(
                text(
                    "DELETE FROM user_account_audit_events WHERE target_user_id IN "
                    f"({account_ids}) OR actor_user_id IN ({account_ids})"
                )
            )
            connection.execute(
                text(f"DELETE FROM external_identities WHERE user_account_id IN ({account_ids})")
            )
            connection.execute(
                text(f"DELETE FROM user_accounts WHERE login_name LIKE '{login_prefix}%'")
            )

    cleanup()
    try:
        with Session(postgres_engine) as setup_session:
            first_admin = bootstrap_admin(
                setup_session,
                login_name=f"{login_prefix}first",
                password_hash=generate_password_hash("synthetic-admin-password"),
                occurred_at=datetime(2026, 7, 15, 9, 16, tzinfo=UTC),
            )
            second_admin = bootstrap_admin(
                setup_session,
                login_name=f"{login_prefix}second",
                password_hash=generate_password_hash("synthetic-admin-password"),
                occurred_at=datetime(2026, 7, 15, 9, 17, tzinfo=UTC),
            )
            target = register_local_member(
                setup_session,
                login_name=f"{login_prefix}target",
                email="stale-target@phase11.invalid",
                display_name="합성 동시성 승인 대상",
                password="synthetic-member-password",
                occurred_at=datetime(2026, 7, 15, 9, 18, tzinfo=UTC),
            )
            setup_session.commit()
            first_admin_id = first_admin.id
            second_admin_id = second_admin.id
            target_id = target.id

        with Session(postgres_engine) as stale_session:
            stale_actor = stale_session.get(UserAccount, first_admin_id)
            stale_target = stale_session.get(UserAccount, target_id)
            assert stale_actor is not None and stale_target is not None

            with Session(postgres_engine) as concurrent_session:
                current_actor = concurrent_session.get(UserAccount, second_admin_id)
                demoted = concurrent_session.get(UserAccount, first_admin_id)
                assert current_actor is not None and demoted is not None
                change_member_role(
                    concurrent_session,
                    actor=current_actor,
                    target=demoted,
                    new_role="MEMBER",
                    occurred_at=datetime(2026, 7, 15, 9, 19, tzinfo=UTC),
                )
                concurrent_session.commit()

            with pytest.raises(MembershipError, match="승인 권한"):
                approve_pending_member(
                    stale_session,
                    actor=stale_actor,
                    target=stale_target,
                    occurred_at=datetime(2026, 7, 15, 9, 20, tzinfo=UTC),
                )
            stale_session.rollback()

        with Session(postgres_engine) as verification_session:
            actor_role = verification_session.scalar(
                select(UserAccount.role).where(UserAccount.id == first_admin_id)
            )
            target_status = verification_session.scalar(
                select(UserAccount.status).where(UserAccount.id == target_id)
            )
            assert actor_role == "MEMBER"
            assert target_status == "PENDING_APPROVAL"
    finally:
        cleanup()


def test_last_active_admin_cannot_be_suspended(membership_session: Session) -> None:
    admin = _active_admin(membership_session)

    with pytest.raises(MembershipError, match="마지막 활성 관리자"):
        change_member_status(
            membership_session,
            actor=admin,
            target=admin,
            new_status="SUSPENDED",
            occurred_at=datetime(2026, 7, 15, 9, 21, tzinfo=UTC),
        )


def test_membership_mutations_write_complete_audit_events(
    membership_session: Session,
) -> None:
    admin = _active_admin(membership_session)
    member = register_local_member(
        membership_session,
        login_name="synthetic-audited-member",
        email="audited-member@example.invalid",
        display_name="합성 감사 회원",
        password="synthetic-member-password",
        occurred_at=datetime(2026, 7, 15, 9, 22, tzinfo=UTC),
    )
    approve_pending_member(
        membership_session,
        actor=admin,
        target=member,
        occurred_at=datetime(2026, 7, 15, 9, 23, tzinfo=UTC),
    )
    change_member_role(
        membership_session,
        actor=admin,
        target=member,
        new_role="ASSISTANT_ADMIN",
        occurred_at=datetime(2026, 7, 15, 9, 24, tzinfo=UTC),
    )
    change_member_status(
        membership_session,
        actor=admin,
        target=member,
        new_status="SUSPENDED",
        occurred_at=datetime(2026, 7, 15, 9, 25, tzinfo=UTC),
    )
    bootstrap_admin(
        membership_session,
        login_name="synthetic-admin",
        password_hash=generate_password_hash("replacement-admin-password"),
        occurred_at=datetime(2026, 7, 15, 9, 26, tzinfo=UTC),
    )
    membership_session.flush()

    member_events = tuple(
        membership_session.scalars(
            select(UserAccountAuditEvent)
            .where(UserAccountAuditEvent.target_user_id == member.id)
            .order_by(UserAccountAuditEvent.occurred_at)
        )
    )
    assert tuple(event.event_type for event in member_events) == (
        "REGISTERED_LOCAL",
        "APPROVED",
        "ROLE_CHANGED",
        "STATUS_CHANGED",
    )
    assert member_events[1].actor_user_id == admin.id
    assert (member_events[1].before_status, member_events[1].after_status) == (
        "PENDING_APPROVAL",
        "ACTIVE",
    )
    assert (member_events[2].before_role, member_events[2].after_role) == (
        "MEMBER",
        "ASSISTANT_ADMIN",
    )
    assert (member_events[3].before_status, member_events[3].after_status) == (
        "ACTIVE",
        "SUSPENDED",
    )
    assert (
        membership_session.scalar(
            select(UserAccountAuditEvent).where(
                UserAccountAuditEvent.target_user_id == admin.id,
                UserAccountAuditEvent.event_type == "PASSWORD_CHANGED",
            )
        )
        is not None
    )


def test_assistant_cannot_approve_self_privileged_or_processed_accounts(
    membership_session: Session,
) -> None:
    admin = _active_admin(membership_session)
    assistant = register_local_member(
        membership_session,
        login_name="synthetic-approval-matrix-assistant",
        email="approval-matrix-assistant@example.invalid",
        display_name="합성 승인 행렬 보조 관리자",
        password="synthetic-assistant-password",
        occurred_at=datetime(2026, 7, 15, 9, 27, tzinfo=UTC),
    )
    approve_pending_member(
        membership_session,
        actor=admin,
        target=assistant,
        occurred_at=datetime(2026, 7, 15, 9, 28, tzinfo=UTC),
    )
    change_member_role(
        membership_session,
        actor=admin,
        target=assistant,
        new_role="ASSISTANT_ADMIN",
        occurred_at=datetime(2026, 7, 15, 9, 29, tzinfo=UTC),
    )
    processed = register_local_member(
        membership_session,
        login_name="synthetic-processed-member",
        email="processed-member@example.invalid",
        display_name="합성 처리 완료 회원",
        password="synthetic-member-password",
        occurred_at=datetime(2026, 7, 15, 9, 30, tzinfo=UTC),
    )
    approve_pending_member(
        membership_session,
        actor=assistant,
        target=processed,
        occurred_at=datetime(2026, 7, 15, 9, 31, tzinfo=UTC),
    )

    with pytest.raises(MembershipError, match="자기 자신"):
        approve_pending_member(
            membership_session,
            actor=assistant,
            target=assistant,
            occurred_at=datetime(2026, 7, 15, 9, 32, tzinfo=UTC),
        )
    for target in (admin, processed):
        with pytest.raises(MembershipError, match="승인 대기 일반 회원"):
            approve_pending_member(
                membership_session,
                actor=assistant,
                target=target,
                occurred_at=datetime(2026, 7, 15, 9, 33, tzinfo=UTC),
            )


def test_concurrent_approval_creates_one_approval_event(postgres_engine: Engine) -> None:
    login_prefix = "phase11-concurrent-approval-"

    def cleanup() -> None:
        with postgres_engine.begin() as connection:
            account_ids = f"SELECT id FROM user_accounts WHERE login_name LIKE '{login_prefix}%'"
            connection.execute(
                text(
                    "DELETE FROM user_account_audit_events WHERE target_user_id IN "
                    f"({account_ids}) OR actor_user_id IN ({account_ids})"
                )
            )
            connection.execute(
                text(f"DELETE FROM external_identities WHERE user_account_id IN ({account_ids})")
            )
            connection.execute(
                text(f"DELETE FROM user_accounts WHERE login_name LIKE '{login_prefix}%'")
            )

    cleanup()
    try:
        with Session(postgres_engine) as setup_session:
            first_admin = bootstrap_admin(
                setup_session,
                login_name=f"{login_prefix}first",
                password_hash=generate_password_hash("synthetic-admin-password"),
                occurred_at=datetime(2026, 7, 15, 9, 34, tzinfo=UTC),
            )
            second_admin = bootstrap_admin(
                setup_session,
                login_name=f"{login_prefix}second",
                password_hash=generate_password_hash("synthetic-admin-password"),
                occurred_at=datetime(2026, 7, 15, 9, 35, tzinfo=UTC),
            )
            target = register_local_member(
                setup_session,
                login_name=f"{login_prefix}target",
                email="concurrent-approval-target@phase11.invalid",
                display_name="합성 동시 승인 대상",
                password="synthetic-member-password",
                occurred_at=datetime(2026, 7, 15, 9, 36, tzinfo=UTC),
            )
            setup_session.commit()
            actor_ids = (first_admin.id, second_admin.id)
            target_id = target.id

        start = Barrier(2)

        def run_approval(actor_id: str) -> str:
            with Session(postgres_engine) as database_session:
                actor = database_session.get(UserAccount, actor_id)
                target_account = database_session.get(UserAccount, target_id)
                assert actor is not None and target_account is not None
                start.wait(timeout=5)
                try:
                    approve_pending_member(
                        database_session,
                        actor=actor,
                        target=target_account,
                        occurred_at=datetime(2026, 7, 15, 9, 37, tzinfo=UTC),
                    )
                    database_session.commit()
                    return "approved"
                except MembershipError:
                    database_session.rollback()
                    return "rejected"

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = tuple(executor.map(run_approval, actor_ids))

        assert sorted(results) == ["approved", "rejected"]
        with Session(postgres_engine) as verification_session:
            stored = verification_session.get(UserAccount, target_id)
            assert stored is not None
            assert stored.status == "ACTIVE"
            approval_events = tuple(
                verification_session.scalars(
                    select(UserAccountAuditEvent).where(
                        UserAccountAuditEvent.target_user_id == target_id,
                        UserAccountAuditEvent.event_type == "APPROVED",
                    )
                )
            )
            assert len(approval_events) == 1
            assert approval_events[0].actor_user_id == stored.approved_by_user_id
    finally:
        cleanup()
