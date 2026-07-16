from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import pytest
from flask.testing import FlaskClient
from joserfc.errors import JoseError
from requests import RequestException
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app import create_app
from app.models import AiProviderCredential, ExternalIdentity, UserAccount
from app.services.membership import (
    approve_pending_member,
    bootstrap_admin,
    change_member_role,
    change_member_status,
    register_local_member,
)


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


@pytest.fixture(autouse=True)
def clean_phase11_accounts(postgres_engine: Engine) -> Iterator[None]:
    yield
    with postgres_engine.begin() as connection:
        account_filter = (
            "SELECT id FROM user_accounts WHERE email LIKE '%@phase11.invalid' "
            "OR login_name LIKE 'phase11-%'"
        )
        connection.execute(
            text(
                "DELETE FROM user_account_audit_events WHERE target_user_id IN "
                f"({account_filter}) "
                "OR actor_user_id IN "
                f"({account_filter})"
            )
        )
        connection.execute(
            text(f"DELETE FROM external_identities WHERE user_account_id IN ({account_filter})")
        )
        connection.execute(
            text(
                "DELETE FROM user_accounts WHERE email LIKE '%@phase11.invalid' "
                "OR login_name LIKE 'phase11-%'"
            )
        )


def _app(postgres_engine: Engine):  # type: ignore[no-untyped-def]
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "ADMIN_USERNAME": "phase11-admin",
            "ADMIN_PASSWORD_HASH": generate_password_hash("phase11-admin-password"),
            "ALLOW_LEGACY_ADMIN_LOGIN": False,
            "GOOGLE_OIDC_ENABLED": False,
        }
    )


def _oidc_app(postgres_engine: Engine):  # type: ignore[no-untyped-def]
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "ADMIN_USERNAME": "phase11-admin",
            "ADMIN_PASSWORD_HASH": generate_password_hash("phase11-admin-password"),
            "ALLOW_LEGACY_ADMIN_LOGIN": False,
            "GOOGLE_OIDC_ENABLED": True,
            "GOOGLE_OIDC_CLIENT_ID": "synthetic-google-client-id",
            "GOOGLE_OIDC_CLIENT_SECRET": "synthetic-google-client-secret",
            "GOOGLE_REDIRECT_URI": "https://alpha.example.invalid/auth/google/callback",
        }
    )


def _bootstrap(postgres_engine: Engine) -> UserAccount:
    with Session(postgres_engine) as database_session:
        admin = bootstrap_admin(
            database_session,
            login_name="phase11-admin",
            password_hash=generate_password_hash("phase11-admin-password"),
            occurred_at=datetime(2026, 7, 15, 10, 0, tzinfo=UTC),
        )
        database_session.commit()
        database_session.refresh(admin)
        database_session.expunge(admin)
        return admin


def _login(client: FlaskClient, username: str, password: str):  # type: ignore[no-untyped-def]
    page = client.get("/auth/login")
    return client.post(
        "/auth/login",
        data={
            "csrf_token": _csrf(page.get_data(as_text=True)),
            "username": username,
            "password": password,
        },
    )


def test_local_signup_ignores_role_tampering_and_blocks_use_until_approval(
    postgres_engine: Engine,
) -> None:
    app = _app(postgres_engine)
    client = app.test_client()
    page = client.get("/auth/register")

    response = client.post(
        "/auth/register",
        data={
            "csrf_token": _csrf(page.get_data(as_text=True)),
            "login_name": "phase11-member",
            "email": "member@phase11.invalid",
            "display_name": "합성 가입 회원",
            "password": "phase11-member-password",
            "password_confirmation": "phase11-member-password",
            "role": "ADMIN",
            "status": "ACTIVE",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/registration-received")
    receipt = client.get(response.headers["Location"])
    assert receipt.status_code == 200
    assert "가입 신청 접수" in receipt.get_data(as_text=True)
    blocked = client.get("/admin/consultations/new")
    assert blocked.status_code == 302
    assert "/auth/login" in blocked.headers["Location"]
    pending_login = _login(client, "phase11-member", "phase11-member-password")
    assert pending_login.status_code == 302
    assert pending_login.headers["Location"].endswith("/auth/pending")
    with Session(postgres_engine) as database_session:
        member = database_session.scalar(
            select(UserAccount).where(UserAccount.email == "member@phase11.invalid")
        )
        assert member is not None
        assert (member.role, member.status) == ("MEMBER", "PENDING_APPROVAL")


def test_duplicate_registration_has_same_external_response_as_new_request(
    postgres_engine: Engine,
) -> None:
    app = _app(postgres_engine)
    client = app.test_client()

    def submit() -> tuple[int, str]:
        page = client.get("/auth/register")
        response = client.post(
            "/auth/register",
            data={
                "csrf_token": _csrf(page.get_data(as_text=True)),
                "login_name": "phase11-duplicate",
                "email": "duplicate@phase11.invalid",
                "display_name": "합성 중복 가입",
                "password": "phase11-member-password",
                "password_confirmation": "phase11-member-password",
            },
        )
        return response.status_code, response.headers["Location"]

    first = submit()
    second = submit()

    assert first == second == (302, "/auth/registration-received")
    with Session(postgres_engine) as database_session:
        members = tuple(
            database_session.scalars(
                select(UserAccount).where(UserAccount.login_name == "phase11-duplicate")
            )
        )
        assert len(members) == 1


def test_database_failure_response_and_log_do_not_expose_registration_fields(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _app(postgres_engine)
    client = app.test_client()
    marker = "synthetic-private-registration-marker"

    def fail_registration(*_args: object, **_kwargs: object) -> None:
        raise OperationalError(
            "INSERT INTO user_accounts (email, display_name, password_hash) VALUES (...) ",
            {"email": f"{marker}@phase11.invalid", "password_hash": marker},
            RuntimeError(marker),
        )

    monkeypatch.setattr("app.auth_routes.register_local_member", fail_registration)
    page = client.get("/auth/register")
    response = client.post(
        "/auth/register",
        data={
            "csrf_token": _csrf(page.get_data(as_text=True)),
            "login_name": "phase11-database-failure",
            "email": f"{marker}@phase11.invalid",
            "display_name": marker,
            "password": "phase11-member-password",
            "password_confirmation": "phase11-member-password",
        },
    )

    assert response.status_code == 503
    assert "잠시 후 다시 시도하세요" in response.get_data(as_text=True)
    assert marker not in response.get_data(as_text=True)
    assert marker not in caplog.text


def test_admin_approves_member_then_member_can_use_consultation(postgres_engine: Engine) -> None:
    _bootstrap(postgres_engine)
    with Session(postgres_engine) as database_session:
        member = register_local_member(
            database_session,
            login_name="phase11-approved-member",
            email="approved@phase11.invalid",
            display_name="합성 승인 회원",
            password="phase11-member-password",
            occurred_at=datetime(2026, 7, 15, 10, 1, tzinfo=UTC),
        )
        database_session.commit()
        member_id = member.id

    app = _app(postgres_engine)
    client = app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["pre_login_marker"] = "must-be-cleared"
    login = _login(client, "phase11-admin", "phase11-admin-password")
    assert login.status_code == 302
    with client.session_transaction() as browser_session:
        assert "pre_login_marker" not in browser_session
    page = client.get("/admin/members")
    assert page.status_code == 200
    approve = client.post(
        f"/admin/members/{member_id}/approve",
        data={"csrf_token": _csrf(page.get_data(as_text=True))},
    )
    assert approve.status_code == 302

    members_page = client.get("/admin/members")
    logout = client.post(
        "/auth/logout",
        data={"csrf_token": _csrf(members_page.get_data(as_text=True))},
    )
    assert logout.status_code == 302
    member_login = _login(client, "phase11-approved-member", "phase11-member-password")
    assert member_login.status_code == 302
    assert member_login.headers["Location"].endswith("/admin/consultations/new")
    consultation = client.get("/admin/consultations/new")
    assert consultation.status_code == 200
    assert "지원자격" in consultation.get_data(as_text=True)


def test_assistant_can_approve_but_cannot_change_rules_or_roles(postgres_engine: Engine) -> None:
    with Session(postgres_engine) as database_session:
        admin = bootstrap_admin(
            database_session,
            login_name="phase11-admin",
            password_hash=generate_password_hash("phase11-admin-password"),
            occurred_at=datetime(2026, 7, 15, 10, 2, tzinfo=UTC),
        )
        assistant = register_local_member(
            database_session,
            login_name="phase11-assistant",
            email="assistant@phase11.invalid",
            display_name="합성 보조 관리자",
            password="phase11-assistant-password",
            occurred_at=datetime(2026, 7, 15, 10, 3, tzinfo=UTC),
        )
        approve_pending_member(
            database_session,
            actor=admin,
            target=assistant,
            occurred_at=datetime(2026, 7, 15, 10, 4, tzinfo=UTC),
        )
        change_member_role(
            database_session,
            actor=admin,
            target=assistant,
            new_role="ASSISTANT_ADMIN",
            occurred_at=datetime(2026, 7, 15, 10, 5, tzinfo=UTC),
        )
        target = register_local_member(
            database_session,
            login_name="phase11-target",
            email="target@phase11.invalid",
            display_name="합성 승인 대상",
            password="phase11-target-password",
            occurred_at=datetime(2026, 7, 15, 10, 6, tzinfo=UTC),
        )
        database_session.commit()
        target_id = target.id

    app = _app(postgres_engine)
    client = app.test_client()
    assert _login(client, "phase11-assistant", "phase11-assistant-password").status_code == 302
    page = client.get("/admin/members")
    assert page.status_code == 200
    assert client.get("/admin/rules").status_code == 403
    role_change = client.post(
        f"/admin/members/{target_id}/role",
        data={"csrf_token": _csrf(page.get_data(as_text=True)), "role": "ADMIN"},
    )
    assert role_change.status_code == 403
    approve = client.post(
        f"/admin/members/{target_id}/approve",
        data={"csrf_token": _csrf(page.get_data(as_text=True))},
    )
    assert approve.status_code == 302


def test_role_change_invalidates_existing_member_session(postgres_engine: Engine) -> None:
    with Session(postgres_engine) as database_session:
        admin = bootstrap_admin(
            database_session,
            login_name="phase11-admin",
            password_hash=generate_password_hash("phase11-admin-password"),
            occurred_at=datetime(2026, 7, 15, 10, 7, tzinfo=UTC),
        )
        member = register_local_member(
            database_session,
            login_name="phase11-session-member",
            email="session@phase11.invalid",
            display_name="합성 세션 회원",
            password="phase11-session-password",
            occurred_at=datetime(2026, 7, 15, 10, 8, tzinfo=UTC),
        )
        approve_pending_member(
            database_session,
            actor=admin,
            target=member,
            occurred_at=datetime(2026, 7, 15, 10, 9, tzinfo=UTC),
        )
        database_session.commit()
        member_id = member.id

    app = _app(postgres_engine)
    client = app.test_client()
    assert _login(client, "phase11-session-member", "phase11-session-password").status_code == 302
    assert client.get("/admin/consultations/new").status_code == 200

    with Session(postgres_engine) as database_session:
        stored_admin = database_session.scalar(
            select(UserAccount).where(UserAccount.login_name == "phase11-admin")
        )
        stored_member = database_session.get(UserAccount, member_id)
        assert stored_admin is not None and stored_member is not None
        change_member_role(
            database_session,
            actor=stored_admin,
            target=stored_member,
            new_role="ASSISTANT_ADMIN",
            occurred_at=datetime(2026, 7, 15, 10, 10, tzinfo=UTC),
        )
        database_session.commit()

    invalidated = client.get("/admin/consultations/new")
    assert invalidated.status_code == 302
    assert "/auth/login" in invalidated.headers["Location"]


@pytest.mark.parametrize("blocked_status", ["REJECTED", "SUSPENDED"])
def test_rejected_or_suspended_member_cannot_use_protected_features(
    postgres_engine: Engine,
    blocked_status: str,
) -> None:
    with Session(postgres_engine) as database_session:
        admin = bootstrap_admin(
            database_session,
            login_name="phase11-admin",
            password_hash=generate_password_hash("phase11-admin-password"),
            occurred_at=datetime(2026, 7, 15, 10, 12, tzinfo=UTC),
        )
        member = register_local_member(
            database_session,
            login_name=f"phase11-{blocked_status.lower()}-member",
            email=f"{blocked_status.lower()}@phase11.invalid",
            display_name="합성 접근 차단 회원",
            password="phase11-member-password",
            occurred_at=datetime(2026, 7, 15, 10, 13, tzinfo=UTC),
        )
        if blocked_status == "SUSPENDED":
            approve_pending_member(
                database_session,
                actor=admin,
                target=member,
                occurred_at=datetime(2026, 7, 15, 10, 14, tzinfo=UTC),
            )
        change_member_status(
            database_session,
            actor=admin,
            target=member,
            new_status=blocked_status,
            occurred_at=datetime(2026, 7, 15, 10, 15, tzinfo=UTC),
        )
        database_session.commit()

    client = _app(postgres_engine).test_client()
    login = _login(
        client,
        f"phase11-{blocked_status.lower()}-member",
        "phase11-member-password",
    )
    assert login.status_code == 302
    assert login.headers["Location"].endswith("/auth/pending")
    blocked = client.get("/admin/consultations/new")
    assert blocked.status_code == 302
    assert blocked.headers["Location"].endswith("/auth/pending")


def test_status_change_invalidates_existing_member_session(postgres_engine: Engine) -> None:
    with Session(postgres_engine) as database_session:
        admin = bootstrap_admin(
            database_session,
            login_name="phase11-admin",
            password_hash=generate_password_hash("phase11-admin-password"),
            occurred_at=datetime(2026, 7, 15, 10, 16, tzinfo=UTC),
        )
        member = register_local_member(
            database_session,
            login_name="phase11-status-session-member",
            email="status-session@phase11.invalid",
            display_name="합성 상태 세션 회원",
            password="phase11-member-password",
            occurred_at=datetime(2026, 7, 15, 10, 17, tzinfo=UTC),
        )
        approve_pending_member(
            database_session,
            actor=admin,
            target=member,
            occurred_at=datetime(2026, 7, 15, 10, 18, tzinfo=UTC),
        )
        database_session.commit()
        member_id = member.id

    app = _app(postgres_engine)
    client = app.test_client()
    assert (
        _login(client, "phase11-status-session-member", "phase11-member-password").status_code
        == 302
    )
    assert client.get("/admin/consultations/new").status_code == 200

    with Session(postgres_engine) as database_session:
        stored_admin = database_session.scalar(
            select(UserAccount).where(UserAccount.login_name == "phase11-admin")
        )
        stored_member = database_session.get(UserAccount, member_id)
        assert stored_admin is not None and stored_member is not None
        change_member_status(
            database_session,
            actor=stored_admin,
            target=stored_member,
            new_status="SUSPENDED",
            occurred_at=datetime(2026, 7, 15, 10, 19, tzinfo=UTC),
        )
        database_session.commit()

    invalidated = client.get("/admin/consultations/new")
    assert invalidated.status_code == 302
    assert "/auth/login" in invalidated.headers["Location"]


def test_bootstrap_password_rotation_invalidates_existing_admin_session(
    postgres_engine: Engine,
) -> None:
    _bootstrap(postgres_engine)
    app = _app(postgres_engine)
    client = app.test_client()
    assert _login(client, "phase11-admin", "phase11-admin-password").status_code == 302
    assert client.get("/admin/rules").status_code == 200

    with Session(postgres_engine) as database_session:
        bootstrap_admin(
            database_session,
            login_name="phase11-admin",
            password_hash=generate_password_hash("replacement-admin-password"),
            occurred_at=datetime(2026, 7, 15, 10, 20, tzinfo=UTC),
        )
        database_session.commit()

    invalidated = client.get("/admin/rules")
    assert invalidated.status_code == 302
    assert "/admin/login" in invalidated.headers["Location"]


def test_local_member_can_use_own_ai_area_but_not_management_pages(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine) as database_session:
        admin = bootstrap_admin(
            database_session,
            login_name="phase11-admin",
            password_hash=generate_password_hash("phase11-admin-password"),
            occurred_at=datetime(2026, 7, 15, 10, 21, tzinfo=UTC),
        )
        member = register_local_member(
            database_session,
            login_name="phase11-capability-member",
            email="capability@phase11.invalid",
            display_name="합성 기능 범위 회원",
            password="phase11-member-password",
            occurred_at=datetime(2026, 7, 15, 10, 22, tzinfo=UTC),
        )
        approve_pending_member(
            database_session,
            actor=admin,
            target=member,
            occurred_at=datetime(2026, 7, 15, 10, 23, tzinfo=UTC),
        )
        database_session.commit()

    client = _app(postgres_engine).test_client()
    assert _login(client, "phase11-capability-member", "phase11-member-password").status_code == 302
    ai_settings = client.get("/admin/ai/settings")
    assert ai_settings.status_code == 200
    assert "내 공급자 키" in ai_settings.get_data(as_text=True)
    assert client.get("/admin/rules").status_code == 403
    assert client.get("/admin/members").status_code == 403


def test_bootstrap_admin_keeps_legacy_actor_ref_and_existing_ai_ownership(
    postgres_engine: Engine,
) -> None:
    _bootstrap(postgres_engine)
    with Session(postgres_engine) as database_session:
        database_session.execute(
            delete(AiProviderCredential).where(
                AiProviderCredential.actor_ref == "phase11-admin",
                AiProviderCredential.provider == "OPENAI",
            )
        )
        database_session.add(
            AiProviderCredential(
                actor_ref="phase11-admin",
                provider="OPENAI",
                encrypted_api_key="synthetic-ciphertext",
                masked_hint="••••old1",
                encryption_version="FERNET_V1",
            )
        )
        database_session.commit()

    try:
        client = _app(postgres_engine).test_client()
        assert _login(client, "phase11-admin", "phase11-admin-password").status_code == 302
        page = client.get("/admin/ai/settings")
        assert page.status_code == 200
        body = page.get_data(as_text=True)
        assert "phase11-admin" in body
        assert "••••old1" in body
    finally:
        with postgres_engine.begin() as connection:
            connection.execute(
                delete(AiProviderCredential).where(
                    AiProviderCredential.actor_ref == "phase11-admin",
                    AiProviderCredential.provider == "OPENAI",
                )
            )


class _SyntheticGoogleClient:
    def authorize_access_token(self) -> dict[str, object]:
        return {
            "access_token": "must-not-be-persisted-or-logged",
            "userinfo": {
                "iss": "https://accounts.google.com",
                "sub": "phase11-google-subject",
                "email": "google@phase11.invalid",
                "email_verified": True,
                "name": "합성 Google 회원",
            },
        }


class _FailingGoogleClient:
    def __init__(self, error: Exception) -> None:
        self.error = error

    def authorize_redirect(self, _redirect_uri: str) -> None:
        raise self.error

    def authorize_access_token(self) -> None:
        raise self.error


def test_google_provider_transport_failure_is_generic_and_secret_free(
    postgres_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _app(postgres_engine)
    secret_detail = "synthetic-provider-secret-must-not-log"
    app.extensions["google_oidc_client"] = _FailingGoogleClient(RequestException(secret_detail))

    response = app.test_client().get("/auth/google/start")

    assert response.status_code == 503
    assert "Google 로그인을 시작할 수 없습니다." in response.get_data(as_text=True)
    assert secret_detail not in response.get_data(as_text=True)
    assert secret_detail not in caplog.text


def test_google_invalid_id_token_failure_is_generic_and_secret_free(
    postgres_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _app(postgres_engine)
    secret_detail = "synthetic-invalid-signature-must-not-log"
    app.extensions["google_oidc_client"] = _FailingGoogleClient(JoseError(secret_detail))

    response = app.test_client().get(
        "/auth/google/callback?code=synthetic-code&state=synthetic-state"
    )

    assert response.status_code == 401
    assert "Google 로그인을 완료할 수 없습니다." in response.get_data(as_text=True)
    assert secret_detail not in response.get_data(as_text=True)
    assert secret_detail not in caplog.text


def test_google_start_uses_state_nonce_and_pkce_without_logging_verifier(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _oidc_app(postgres_engine)
    oidc_client = app.extensions["google_oidc_client"]
    monkeypatch.setattr(
        oidc_client,
        "load_server_metadata",
        lambda: {
            "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
        },
    )
    caplog.set_level("DEBUG")

    response = app.test_client().get("/auth/google/start")

    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["Location"]).query)
    assert query["scope"] == ["openid email profile"]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) >= 43
    assert len(query["state"][0]) >= 20
    assert len(query["nonce"][0]) >= 20
    assert "code_verifier" not in caplog.text


def test_google_callback_rejects_mismatched_state_before_token_exchange(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _oidc_app(postgres_engine)
    oidc_client = app.extensions["google_oidc_client"]

    def unexpected_exchange(**_kwargs: object) -> None:
        raise AssertionError("state 검증 전에 token 교환을 시도했습니다.")

    monkeypatch.setattr(oidc_client, "fetch_access_token", unexpected_exchange)
    response = app.test_client().get(
        "/auth/google/callback?code=synthetic-code-must-not-log&state=mismatched-state-must-not-log"
    )

    assert response.status_code == 401
    assert "Google 로그인을 완료할 수 없습니다." in response.get_data(as_text=True)
    assert "synthetic-code-must-not-log" not in caplog.text
    assert "mismatched-state-must-not-log" not in caplog.text


def test_google_callback_creates_pending_member_without_storing_token(
    postgres_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    app = _app(postgres_engine)
    app.extensions["google_oidc_client"] = _SyntheticGoogleClient()
    client = app.test_client()
    with client.session_transaction() as browser_session:
        browser_session["_state_google_synthetic"] = {
            "data": {"nonce": "must-not-remain", "code_verifier": "must-not-remain"}
        }
        browser_session["oauth_code"] = "must-not-remain"

    response = client.get(
        "/auth/google/callback?code=synthetic-code-must-not-log&state=synthetic-state-must-not-log"
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/pending")
    assert "synthetic-code-must-not-log" not in response.get_data(as_text=True)
    assert "synthetic-state-must-not-log" not in caplog.text
    assert "must-not-be-persisted-or-logged" not in caplog.text
    with client.session_transaction() as browser_session:
        assert set(browser_session) == {
            "admin_csrf_token",
            "authenticated_at",
            "auth_version",
            "csrf_token",
            "user_id",
        }
        assert "must-not-remain" not in repr(dict(browser_session))
    with Session(postgres_engine) as database_session:
        member = database_session.scalar(
            select(UserAccount).where(UserAccount.email == "google@phase11.invalid")
        )
        assert member is not None
        assert (member.role, member.status) == ("MEMBER", "PENDING_APPROVAL")
        identity = database_session.scalar(
            select(ExternalIdentity).where(
                ExternalIdentity.provider_subject == "phase11-google-subject"
            )
        )
        assert identity is not None
        assert identity.user_account_id == member.id


def test_approved_google_identity_can_log_in_without_creating_another_account(
    postgres_engine: Engine,
) -> None:
    _bootstrap(postgres_engine)
    app = _app(postgres_engine)
    app.extensions["google_oidc_client"] = _SyntheticGoogleClient()
    first_client = app.test_client()

    first = first_client.get("/auth/google/callback?code=first&state=first")
    assert first.status_code == 302
    assert first.headers["Location"].endswith("/auth/pending")

    with Session(postgres_engine) as database_session:
        admin = database_session.scalar(
            select(UserAccount).where(UserAccount.login_name == "phase11-admin")
        )
        member = database_session.scalar(
            select(UserAccount).where(UserAccount.email == "google@phase11.invalid")
        )
        assert admin is not None and member is not None
        approve_pending_member(
            database_session,
            actor=admin,
            target=member,
            occurred_at=datetime(2026, 7, 15, 10, 11, tzinfo=UTC),
        )
        database_session.commit()
        member_id = member.id

    second_client = app.test_client()
    second = second_client.get("/auth/google/callback?code=second&state=second")

    assert second.status_code == 302
    assert second.headers["Location"].endswith("/admin/consultations/new")
    with Session(postgres_engine) as database_session:
        accounts = tuple(
            database_session.scalars(
                select(UserAccount).where(UserAccount.email == "google@phase11.invalid")
            )
        )
        assert len(accounts) == 1
        assert accounts[0].id == member_id
        assert accounts[0].last_login_at is not None
