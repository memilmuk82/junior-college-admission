from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from urllib.parse import parse_qs, urlparse

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from app import create_app
from app.models import AccountAuthToken, UserAccount, new_id
from app.services.membership import (
    approve_pending_member,
    bootstrap_admin,
    register_local_member,
)

ACCOUNT_EMAIL = "student@route19.invalid"
ADMIN_LOGIN = "route19-admin"
ADMIN_PASSWORD = "route19-admin-password"
ORIGINAL_PASSWORD = "route19-원래-비밀번호"
CHANGED_PASSWORD = "route19-변경-비밀번호"
RESET_PASSWORD = "route19-재설정-비밀번호"


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _message_token(message: EmailMessage, *, expected_path: str) -> str:
    link = next(
        line.strip()
        for line in message.get_content().splitlines()
        if line.strip().startswith("https://")
    )
    parsed = urlparse(link)
    assert parsed.path == expected_path
    tokens = parse_qs(parsed.query).get("token")
    assert tokens is not None and len(tokens) == 1
    return tokens[0]


def _login(client: FlaskClient, identifier: str, password: str):  # type: ignore[no-untyped-def]
    page = client.get("/auth/login")
    assert page.status_code == 200
    return client.post(
        "/auth/login",
        data={
            "csrf_token": _csrf(page.get_data(as_text=True)),
            "username": identifier,
            "password": password,
        },
    )


def _delete_synthetic_accounts(engine: Engine) -> None:
    with engine.begin() as connection:
        account_filter = (
            "SELECT id FROM user_accounts "
            "WHERE email LIKE '%@route19.invalid' OR login_name LIKE 'route19-%'"
        )
        connection.execute(
            text(
                "DELETE FROM user_account_audit_events "
                f"WHERE target_user_id IN ({account_filter}) "
                f"OR actor_user_id IN ({account_filter})"
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
                "DELETE FROM user_accounts "
                "WHERE email LIKE '%@route19.invalid' OR login_name LIKE 'route19-%'"
            )
        )


@pytest.fixture(autouse=True)
def clean_phase19_route_accounts(postgres_engine: Engine) -> Iterator[None]:
    _delete_synthetic_accounts(postgres_engine)
    try:
        yield
    finally:
        _delete_synthetic_accounts(postgres_engine)


@pytest.fixture
def phase19_app(postgres_engine: Engine) -> Iterator[Flask]:
    outbox: list[EmailMessage] = []
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "route19-test-only-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "ADMIN_USERNAME": ADMIN_LOGIN,
            "ADMIN_PASSWORD_HASH": generate_password_hash(ADMIN_PASSWORD),
            "ALLOW_LEGACY_ADMIN_LOGIN": False,
            "GOOGLE_OIDC_ENABLED": False,
            "PUBLIC_BASE_URL": "https://accounts.route19.invalid",
            "ACCOUNT_EMAIL_ENABLED": True,
            "EMAIL_FROM_ADDRESS": "accounts@route19.invalid",
            "ACCOUNT_EMAIL_OUTBOX": outbox,
        }
    )
    with Session(postgres_engine) as database_session:
        bootstrap_admin(
            database_session,
            login_name=ADMIN_LOGIN,
            password_hash=generate_password_hash(ADMIN_PASSWORD),
            occurred_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        database_session.commit()
    yield app


def test_complete_email_account_password_workflow(
    phase19_app: Flask,
    postgres_engine: Engine,
) -> None:
    outbox = phase19_app.config["ACCOUNT_EMAIL_OUTBOX"]
    assert isinstance(outbox, list)
    signup_client = phase19_app.test_client()

    registration_page = signup_client.get("/auth/register?account_type=student")
    registration_body = registration_page.get_data(as_text=True)
    assert registration_page.status_code == 200
    assert "학생 회원가입" in registration_body
    assert 'name="login_name"' not in registration_body
    assert 'name="email"' in registration_body
    assert 'name="password_confirmation"' in registration_body

    registered = signup_client.post(
        "/auth/register",
        data={
            "csrf_token": _csrf(registration_body),
            "account_type": "student",
            "email": ACCOUNT_EMAIL,
            "display_name": "합성 이메일 학생",
            "password": ORIGINAL_PASSWORD,
            "password_confirmation": ORIGINAL_PASSWORD,
            "role": "ADMIN",
            "status": "ACTIVE",
        },
    )
    assert registered.status_code == 302
    assert registered.headers["Location"].endswith(
        "/auth/registration-received?account_type=student"
    )
    assert len(outbox) == 1

    with Session(postgres_engine) as database_session:
        account = database_session.scalar(
            select(UserAccount).where(UserAccount.email == ACCOUNT_EMAIL)
        )
        assert account is not None
        account_id = account.id
        assert (account.login_name, account.role, account.status) == (
            None,
            "STUDENT",
            "PENDING_APPROVAL",
        )
        assert account.email_verified_at is None
        verification_record = database_session.scalar(
            select(AccountAuthToken).where(
                AccountAuthToken.user_account_id == account_id,
                AccountAuthToken.purpose == "EMAIL_VERIFICATION",
            )
        )
        assert verification_record is not None
        assert verification_record.consumed_at is None

    unverified_login = _login(signup_client, ACCOUNT_EMAIL, ORIGINAL_PASSWORD)
    assert unverified_login.status_code == 401
    assert "로그인 정보를 확인하세요" in unverified_login.get_data(as_text=True)

    verification_token = _message_token(outbox[0], expected_path="/auth/email/verify")
    assert hashlib.sha256(verification_token.encode()).hexdigest() == (
        verification_record.token_digest
    )
    verification_preview = signup_client.get(f"/auth/email/verify?token={verification_token}")
    assert verification_preview.status_code == 200
    assert "이메일 주소 확인" in verification_preview.get_data(as_text=True)
    with Session(postgres_engine) as database_session:
        previewed = database_session.get(AccountAuthToken, verification_record.id)
        assert previewed is not None and previewed.consumed_at is None

    verified = signup_client.post(
        "/auth/email/verify",
        data={
            "csrf_token": _csrf(verification_preview.get_data(as_text=True)),
            "token": verification_token,
        },
    )
    assert verified.status_code == 303
    assert verified.headers["Location"].endswith("/auth/login?message=email_verified")
    assert signup_client.get(f"/auth/email/verify?token={verification_token}").status_code == 400

    with Session(postgres_engine) as database_session:
        account = database_session.get(UserAccount, account_id)
        consumed = database_session.get(AccountAuthToken, verification_record.id)
        assert account is not None and account.email_verified_at is not None
        assert consumed is not None and consumed.consumed_at is not None

    admin_client = phase19_app.test_client()
    assert _login(admin_client, ADMIN_LOGIN, ADMIN_PASSWORD).status_code == 302
    members_page = admin_client.get("/admin/members")
    members_body = members_page.get_data(as_text=True)
    assert members_page.status_code == 200
    assert ACCOUNT_EMAIL in members_body
    assert "이메일 인증 완료" in members_body
    approved = admin_client.post(
        f"/admin/members/{account_id}/approve",
        data={"csrf_token": _csrf(members_body)},
    )
    assert approved.status_code == 302
    assert approved.headers["Location"].endswith("/admin/members?message=approved")

    member_client = phase19_app.test_client()
    stale_member_client = phase19_app.test_client()
    member_login = _login(member_client, ACCOUNT_EMAIL.upper(), ORIGINAL_PASSWORD)
    stale_login = _login(stale_member_client, ACCOUNT_EMAIL, ORIGINAL_PASSWORD)
    assert member_login.status_code == 302
    assert member_login.headers["Location"].endswith("/dashboard")
    assert stale_login.status_code == 302

    security_page = member_client.get("/account/security")
    security_body = security_page.get_data(as_text=True)
    assert security_page.status_code == 200
    assert "회원정보·로그인 보안" in security_body
    assert ACCOUNT_EMAIL in security_body
    assert "인증 완료" in security_body
    changed = member_client.post(
        "/account/security/password",
        data={
            "csrf_token": _csrf(security_body),
            "current_password": ORIGINAL_PASSWORD,
            "new_password": CHANGED_PASSWORD,
            "new_password_confirmation": CHANGED_PASSWORD,
        },
    )
    assert changed.status_code == 303
    assert changed.headers["Location"].endswith("/account/security?message=password_changed")
    changed_page = member_client.get(changed.headers["Location"])
    assert changed_page.status_code == 200
    assert "비밀번호를 변경했습니다" in changed_page.get_data(as_text=True)
    stale_session = stale_member_client.get("/account/security")
    assert stale_session.status_code == 302
    assert "/auth/login" in stale_session.headers["Location"]

    old_password_login = _login(phase19_app.test_client(), ACCOUNT_EMAIL, ORIGINAL_PASSWORD)
    assert old_password_login.status_code == 401
    assert _login(phase19_app.test_client(), ACCOUNT_EMAIL, CHANGED_PASSWORD).status_code == 302

    reset_request_client = phase19_app.test_client()
    forgot_page = reset_request_client.get("/auth/password/forgot")
    known_request = reset_request_client.post(
        "/auth/password/forgot",
        data={"csrf_token": _csrf(forgot_page.get_data(as_text=True)), "email": ACCOUNT_EMAIL},
    )
    assert known_request.status_code == 303
    assert known_request.headers["Location"].endswith("/auth/password/requested")
    assert len(outbox) == 2
    reset_token = _message_token(outbox[-1], expected_path="/auth/password/reset")

    unknown_client = phase19_app.test_client()
    unknown_page = unknown_client.get("/auth/password/forgot")
    unknown_request = unknown_client.post(
        "/auth/password/forgot",
        data={
            "csrf_token": _csrf(unknown_page.get_data(as_text=True)),
            "email": "missing@route19.invalid",
        },
    )
    assert unknown_request.status_code == known_request.status_code
    assert unknown_request.headers["Location"] == known_request.headers["Location"]
    assert len(outbox) == 2

    reset_preview = reset_request_client.get(f"/auth/password/reset?token={reset_token}")
    assert reset_preview.status_code == 200
    assert "새 비밀번호 설정" in reset_preview.get_data(as_text=True)
    reset_digest = hashlib.sha256(reset_token.encode()).hexdigest()
    with Session(postgres_engine) as database_session:
        reset_record = database_session.scalar(
            select(AccountAuthToken).where(
                AccountAuthToken.token_digest == reset_digest,
                AccountAuthToken.purpose == "PASSWORD_RESET",
            )
        )
        assert reset_record is not None and reset_record.consumed_at is None
        reset_record_id = reset_record.id

    mismatch = reset_request_client.post(
        "/auth/password/reset",
        data={
            "csrf_token": _csrf(reset_preview.get_data(as_text=True)),
            "token": reset_token,
            "new_password": RESET_PASSWORD,
            "new_password_confirmation": "route19-다른-비밀번호",
        },
    )
    mismatch_body = mismatch.get_data(as_text=True)
    assert mismatch.status_code == 400
    assert "비밀번호 확인이 일치하지 않습니다" in mismatch_body
    assert f'name="token" value="{reset_token}"' in mismatch_body
    assert 'name="new_password"' in mismatch_body

    too_short = reset_request_client.post(
        "/auth/password/reset",
        data={
            "csrf_token": _csrf(mismatch_body),
            "token": reset_token,
            "new_password": "짧은암호",
            "new_password_confirmation": "짧은암호",
        },
    )
    too_short_body = too_short.get_data(as_text=True)
    assert too_short.status_code == 400
    assert "12~256자" in too_short_body
    assert f'name="token" value="{reset_token}"' in too_short_body

    reset = reset_request_client.post(
        "/auth/password/reset",
        data={
            "csrf_token": _csrf(too_short_body),
            "token": reset_token,
            "new_password": RESET_PASSWORD,
            "new_password_confirmation": RESET_PASSWORD,
        },
    )
    assert reset.status_code == 303
    assert reset.headers["Location"].endswith("/auth/login?message=password_reset")
    with Session(postgres_engine) as database_session:
        account = database_session.get(UserAccount, account_id)
        reset_record = database_session.get(AccountAuthToken, reset_record_id)
        assert account is not None and account.password_hash is not None
        assert check_password_hash(account.password_hash, RESET_PASSWORD)
        assert reset_record is not None and reset_record.consumed_at is not None

    invalidated_by_reset = member_client.get("/account/security")
    assert invalidated_by_reset.status_code == 302
    assert "/auth/login" in invalidated_by_reset.headers["Location"]
    assert _login(phase19_app.test_client(), ACCOUNT_EMAIL, CHANGED_PASSWORD).status_code == 401
    final_login = _login(phase19_app.test_client(), ACCOUNT_EMAIL, RESET_PASSWORD)
    assert final_login.status_code == 302
    assert final_login.headers["Location"].endswith("/dashboard")


def test_demo_account_security_mutation_is_forbidden(
    phase19_app: Flask,
    postgres_engine: Engine,
) -> None:
    occurred_at = datetime.now(UTC)
    demo_id = new_id()
    original_hash = generate_password_hash("route19-demo-password")
    with Session(postgres_engine) as database_session:
        admin = database_session.scalar(
            select(UserAccount).where(UserAccount.login_name == ADMIN_LOGIN)
        )
        assert admin is not None
        database_session.add(
            UserAccount(
                id=demo_id,
                actor_ref="demo:role:route19-security",
                login_name="route19-demo-student",
                email="demo-student@route19.invalid",
                display_name="합성 읽기 전용 학생",
                password_hash=original_hash,
                role="STUDENT",
                status="ACTIVE",
                auth_version=1,
                email_verified_at=occurred_at,
                approved_by_user_id=admin.id,
                approved_at=occurred_at,
            )
        )
        database_session.commit()

    client = phase19_app.test_client()
    assert _login(client, "route19-demo-student", "route19-demo-password").status_code == 302
    security_page = client.get("/account/security")
    security_body = security_page.get_data(as_text=True)
    assert security_page.status_code == 200
    assert "읽기 전용 체험 계정" in security_body
    forbidden = client.post(
        "/account/security/password",
        data={
            "csrf_token": _csrf(security_body),
            "current_password": "route19-demo-password",
            "new_password": "route19-demo-new-password",
            "new_password_confirmation": "route19-demo-new-password",
        },
    )
    assert forbidden.status_code == 403
    with Session(postgres_engine) as database_session:
        demo = database_session.get(UserAccount, demo_id)
        assert demo is not None and demo.password_hash is not None
        assert check_password_hash(demo.password_hash, "route19-demo-password")


def test_email_change_resend_and_expired_token_routes(
    phase19_app: Flask,
    postgres_engine: Engine,
) -> None:
    occurred_at = datetime.now(UTC)
    password = "route19-이메일-변경-비밀번호"
    with Session(postgres_engine) as database_session:
        admin = database_session.scalar(
            select(UserAccount).where(UserAccount.login_name == ADMIN_LOGIN)
        )
        assert admin is not None
        admin_email = admin.email
        member = register_local_member(
            database_session,
            login_name="route19-email-change-member",
            email="email-change@route19.invalid",
            display_name="합성 이메일 변경 회원",
            password=password,
            occurred_at=occurred_at - timedelta(minutes=3),
        )
        member.email_verified_at = occurred_at - timedelta(minutes=2)
        approve_pending_member(
            database_session,
            actor=admin,
            target=member,
            occurred_at=occurred_at - timedelta(minutes=1),
        )
        database_session.commit()
        member_id = member.id

    outbox = phase19_app.config["ACCOUNT_EMAIL_OUTBOX"]
    assert isinstance(outbox, list)
    client = phase19_app.test_client()
    assert _login(client, "route19-email-change-member", password).status_code == 302
    security_page = client.get("/account/security")
    requested = client.post(
        "/account/security/email",
        data={
            "csrf_token": _csrf(security_page.get_data(as_text=True)),
            "email": "changed@route19.invalid",
            "current_password": password,
        },
    )
    assert requested.status_code == 303
    assert requested.headers["Location"].endswith("/account/security?message=email_requested")
    assert len(outbox) == 1
    change_token = _message_token(outbox[-1], expected_path="/auth/email/verify")
    preview = client.get(f"/auth/email/verify?token={change_token}")
    assert preview.status_code == 200
    changed = client.post(
        "/auth/email/verify",
        data={"csrf_token": _csrf(preview.get_data(as_text=True)), "token": change_token},
    )
    assert changed.status_code == 303
    with Session(postgres_engine) as database_session:
        stored_member = database_session.get(UserAccount, member_id)
        assert stored_member is not None
        assert stored_member.email == "changed@route19.invalid"
        assert stored_member.email_verified_at is not None

    current_security = client.get("/account/security")
    duplicate_request = client.post(
        "/account/security/email",
        data={
            "csrf_token": _csrf(current_security.get_data(as_text=True)),
            "email": admin_email,
            "current_password": password,
        },
    )
    assert duplicate_request.status_code == 303
    assert duplicate_request.headers["Location"].endswith(
        "/account/security?message=email_requested"
    )
    assert len(outbox) == 1

    signup = phase19_app.test_client()
    register_page = signup.get("/auth/register?account_type=student")
    registered = signup.post(
        "/auth/register",
        data={
            "csrf_token": _csrf(register_page.get_data(as_text=True)),
            "account_type": "student",
            "email": "resend@route19.invalid",
            "display_name": "합성 재발송 회원",
            "password": "route19-재발송-비밀번호",
            "password_confirmation": "route19-재발송-비밀번호",
        },
    )
    assert registered.status_code == 302
    first_resend_token = _message_token(outbox[-1], expected_path="/auth/email/verify")
    resend_page = signup.get("/auth/email/resend")
    resent = signup.post(
        "/auth/email/resend",
        data={
            "csrf_token": _csrf(resend_page.get_data(as_text=True)),
            "email": "resend@route19.invalid",
        },
    )
    assert resent.status_code == 303
    assert signup.get(f"/auth/email/verify?token={first_resend_token}").status_code == 200

    expired_raw_token = "route19-expired-reset-token"
    with Session(postgres_engine) as database_session:
        stored_member = database_session.get(UserAccount, member_id)
        assert stored_member is not None
        database_session.add(
            AccountAuthToken(
                user_account_id=stored_member.id,
                purpose="PASSWORD_RESET",
                token_digest=hashlib.sha256(expired_raw_token.encode()).hexdigest(),
                issued_auth_version=stored_member.auth_version,
                target_email=stored_member.email,
                created_at=occurred_at - timedelta(minutes=2),
                updated_at=occurred_at - timedelta(minutes=2),
                expires_at=occurred_at - timedelta(minutes=1),
            )
        )
        database_session.commit()
    expired = signup.get(f"/auth/password/reset?token={expired_raw_token}")
    expired_body = expired.get_data(as_text=True)
    assert expired.status_code == 400
    assert "유효하지 않거나 만료" in expired_body
    assert 'name="new_password"' not in expired_body


def test_pending_account_cannot_change_login_email_from_security_page(
    phase19_app: Flask,
    postgres_engine: Engine,
) -> None:
    occurred_at = datetime.now(UTC)
    password = "route19-pending-email-password"
    with Session(postgres_engine) as database_session:
        pending = register_local_member(
            database_session,
            login_name="route19-pending-email-member",
            email="pending-email@route19.invalid",
            display_name="합성 승인 대기 회원",
            password=password,
            occurred_at=occurred_at,
        )
        pending.email_verified_at = occurred_at
        database_session.commit()

    outbox = phase19_app.config["ACCOUNT_EMAIL_OUTBOX"]
    assert isinstance(outbox, list)
    client = phase19_app.test_client()
    login = _login(client, "route19-pending-email-member", password)
    assert login.status_code == 302

    security_page = client.get("/account/security")
    assert security_page.status_code == 200
    blocked = client.post(
        "/account/security/email",
        data={
            "csrf_token": _csrf(security_page.get_data(as_text=True)),
            "email": "pending-email-changed@route19.invalid",
            "current_password": password,
        },
    )

    assert blocked.status_code == 403
    assert "활성 계정에서만 로그인 이메일을 변경" in blocked.get_data(as_text=True)
    assert outbox == []
