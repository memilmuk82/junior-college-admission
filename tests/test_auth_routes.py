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
from werkzeug.security import check_password_hash, generate_password_hash

from app import create_app
from app.models import (
    AiProviderCredential,
    ExternalIdentity,
    UserAccount,
    UserAccountAuditEvent,
)
from app.services.membership import (
    DEMO_ROLE_ACTOR_REFS,
    DEMO_ROLE_LOGIN_NAMES,
    MembershipError,
    approve_pending_member,
    authenticate_local_member,
    bootstrap_admin,
    bootstrap_demo_member,
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
            "OR login_name LIKE 'phase11-%' OR actor_ref = 'demo:public' "
            "OR actor_ref LIKE 'demo:role:%'"
        )
        connection.execute(
            text("DELETE FROM ai_consultation_drafts WHERE actor_ref LIKE 'demo:role:%:session:%'")
        )
        connection.execute(
            text("DELETE FROM ai_provider_credentials WHERE actor_ref LIKE 'demo:role:%:session:%'")
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
                "OR login_name LIKE 'phase11-%' OR actor_ref = 'demo:public' "
                "OR actor_ref LIKE 'demo:role:%'"
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
            "PUBLIC_BASE_URL": "https://phase11.example.invalid",
            "ACCOUNT_EMAIL_ENABLED": True,
            "EMAIL_FROM_ADDRESS": "accounts@phase11.example.invalid",
            "ACCOUNT_EMAIL_OUTBOX": [],
            "DEMO_LOGIN_NAME": "phase11-demo-teacher",
            "DEMO_PUBLIC_PASSWORD": "phase11-demo-password",
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
            "PUBLIC_BASE_URL": "https://alpha.example.invalid",
            "ACCOUNT_EMAIL_ENABLED": True,
            "EMAIL_FROM_ADDRESS": "accounts@phase11.example.invalid",
            "ACCOUNT_EMAIL_OUTBOX": [],
        }
    )


def _latest_account_email_token(app) -> str:  # type: ignore[no-untyped-def]
    outbox = app.config["ACCOUNT_EMAIL_OUTBOX"]
    assert isinstance(outbox, list) and outbox
    body = outbox[-1].get_content()
    link = next(line for line in body.splitlines() if line.startswith("https://"))
    token = parse_qs(urlparse(link).query).get("token")
    assert token is not None and len(token) == 1
    return token[0]


def _verify_latest_account_email(client: FlaskClient, app) -> None:  # type: ignore[no-untyped-def]
    token = _latest_account_email_token(app)
    page = client.get(f"/auth/email/verify?token={token}")
    assert page.status_code == 200
    response = client.post(
        "/auth/email/verify",
        data={"csrf_token": _csrf(page.get_data(as_text=True)), "token": token},
    )
    assert response.status_code == 303


def _set_google_login_intent(client: FlaskClient) -> None:
    with client.session_transaction() as browser_session:
        browser_session["google_oidc_intent"] = {
            "kind": "login",
            "user_id": None,
            "auth_version": None,
            "requested_next": None,
            "issued_at": datetime.now(UTC).isoformat(),
            "nonce": "synthetic-google-intent-nonce",
        }


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


def _bootstrap_demo(postgres_engine: Engine) -> UserAccount:
    with Session(postgres_engine) as database_session:
        admin = database_session.scalar(
            select(UserAccount).where(UserAccount.login_name == "phase11-admin")
        )
        if admin is None:
            admin = bootstrap_admin(
                database_session,
                login_name="phase11-admin",
                password_hash=generate_password_hash("phase11-admin-password"),
                occurred_at=datetime(2026, 7, 15, 11, 0, tzinfo=UTC),
            )
        demo = bootstrap_demo_member(
            database_session,
            login_name="phase11-demo-teacher",
            public_password="phase11-demo-password",
            approved_by=admin,
            occurred_at=datetime(2026, 7, 15, 11, 1, tzinfo=UTC),
        )
        database_session.commit()
        database_session.refresh(demo)
        database_session.expunge(demo)
        return demo


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
    unverified_login = _login(client, "member@phase11.invalid", "phase11-member-password")
    assert unverified_login.status_code == 401
    _verify_latest_account_email(client, app)
    pending_login = _login(client, "member@phase11.invalid", "phase11-member-password")
    assert pending_login.status_code == 302
    assert pending_login.headers["Location"].endswith("/auth/pending")
    with Session(postgres_engine) as database_session:
        member = database_session.scalar(
            select(UserAccount).where(UserAccount.email == "member@phase11.invalid")
        )
        assert member is not None
        assert (member.role, member.status) == ("MEMBER", "PENDING_APPROVAL")
        assert member.login_name is None
        assert member.email_verified_at is not None


@pytest.mark.parametrize(
    ("account_type", "expected_role", "heading"),
    (("student", "STUDENT", "학생 회원가입"), ("teacher", "TEACHER", "교사 회원가입")),
)
def test_role_specific_local_registration_preserves_requested_account_type(
    postgres_engine: Engine,
    account_type: str,
    expected_role: str,
    heading: str,
) -> None:
    app = _app(postgres_engine)
    client = app.test_client()
    page = client.get(f"/auth/register?account_type={account_type}")
    body = page.get_data(as_text=True)
    assert heading in body
    assert 'name="account_type" value="' + account_type + '"' in body

    response = client.post(
        "/auth/register",
        data={
            "csrf_token": _csrf(body),
            "account_type": account_type,
            "login_name": f"phase11-{account_type}-request",
            "email": f"{account_type}-request@phase11.invalid",
            "display_name": f"합성 {heading}",
            "password": "phase11-member-password",
            "password_confirmation": "phase11-member-password",
            "role": "ADMIN",
            "status": "ACTIVE",
        },
    )

    assert response.status_code == 302
    with Session(postgres_engine) as database_session:
        account = database_session.scalar(
            select(UserAccount).where(
                UserAccount.email == f"{account_type}-request@phase11.invalid"
            )
        )
        assert account is not None
        assert (account.role, account.status) == (expected_role, "PENDING_APPROVAL")
        assert account.login_name is None
        assert account.email_verified_at is None


@pytest.mark.parametrize(
    ("account_type", "expected_role", "destination"),
    (
        ("student", "STUDENT", "/dashboard"),
        ("teacher", "TEACHER", "/dashboard"),
    ),
)
def test_admin_approves_role_specific_registration_through_member_route(
    postgres_engine: Engine,
    account_type: str,
    expected_role: str,
    destination: str,
) -> None:
    _bootstrap(postgres_engine)
    with Session(postgres_engine) as database_session:
        account = register_local_member(
            database_session,
            login_name=f"phase11-{account_type}-approval",
            email=f"{account_type}-approval@phase11.invalid",
            display_name=f"합성 {expected_role} 승인 대상",
            password="phase11-member-password",
            requested_role=expected_role,
            occurred_at=datetime(2026, 7, 19, 1, 0, tzinfo=UTC),
        )
        database_session.commit()
        account_id = account.id

    client = _app(postgres_engine).test_client()
    assert _login(client, "phase11-admin", "phase11-admin-password").status_code == 302
    page = client.get("/admin/members")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert expected_role in body
    approve = client.post(
        f"/admin/members/{account_id}/approve",
        data={"csrf_token": _csrf(body)},
    )
    assert approve.status_code == 302
    assert approve.headers["Location"].endswith("/admin/members?message=approved")

    with Session(postgres_engine) as database_session:
        stored = database_session.get(UserAccount, account_id)
        assert stored is not None
        assert (stored.role, stored.status) == (expected_role, "ACTIVE")
        assert stored.approved_by_user_id is not None
        assert stored.approved_at is not None

    members_page = client.get("/admin/members")
    client.post(
        "/auth/logout",
        data={"csrf_token": _csrf(members_page.get_data(as_text=True))},
    )
    login = _login(
        client,
        f"phase11-{account_type}-approval",
        "phase11-member-password",
    )
    assert login.status_code == 302
    assert login.headers["Location"].endswith(destination)


def test_public_demo_member_is_idempotent_active_and_cannot_use_mutating_features(
    postgres_engine: Engine,
) -> None:
    first = _bootstrap_demo(postgres_engine)
    second = _bootstrap_demo(postgres_engine)

    assert first.id == second.id
    assert first.actor_ref == "demo:public"
    assert (first.role, first.status) == ("MEMBER", "ACTIVE")
    client = _app(postgres_engine).test_client()
    login_page = client.get("/auth/login")
    login_body = login_page.get_data(as_text=True)
    assert "포트폴리오 공개 체험 계정" in login_body
    assert "phase11-demo-teacher" in login_body
    assert "phase11-demo-password" in login_body

    login = _login(client, "phase11-demo-teacher", "phase11-demo-password")
    assert login.status_code == 302
    assert login.headers["Location"].endswith("/calculate?example=1")

    form_page = client.get(login.headers["Location"])
    body = form_page.get_data(as_text=True)
    assert form_page.status_code == 200
    assert "합성 예시 성적을 불러왔습니다" in body
    assert "가상 미래전문대" not in body
    records_page = client.get("/account/records")
    assert records_page.status_code == 200
    records_body = records_page.get_data(as_text=True)
    assert "합성 성적 체험" in records_body
    assert "빅데이터 프로그래밍" in records_body
    assert (
        client.get("/admin/consultations/new").headers["Location"].endswith("/calculate?example=1")
    )

    assert client.get("/admin/ai/settings").status_code == 403
    assert client.get("/admin/rules").status_code == 403
    assert client.get("/input/review/does-not-exist").status_code == 404

    with Session(postgres_engine) as database_session:
        synthetic_institutions = database_session.scalar(
            text("SELECT count(*) FROM institutions WHERE code = 'DEMO_SYNTHETIC_U'")
        )
        assert synthetic_institutions == 0


def test_public_demo_target_rejects_role_and_status_mutations_but_ordinary_member_allows_them(
    postgres_engine: Engine,
) -> None:
    demo = _bootstrap_demo(postgres_engine)
    with Session(postgres_engine) as database_session:
        admin = database_session.scalar(
            select(UserAccount).where(UserAccount.login_name == "phase11-admin")
        )
        stored_demo = database_session.get(UserAccount, demo.id)
        ordinary = register_local_member(
            database_session,
            login_name="phase11-ordinary-target",
            email="ordinary-target@phase11.invalid",
            display_name="합성 일반 변경 대상",
            password="phase11-ordinary-password",
            occurred_at=datetime(2026, 7, 15, 11, 2, tzinfo=UTC),
        )
        assert admin is not None and stored_demo is not None
        approve_pending_member(
            database_session,
            actor=admin,
            target=ordinary,
            occurred_at=datetime(2026, 7, 15, 11, 3, tzinfo=UTC),
        )

        with pytest.raises(MembershipError, match="공개 데모 계정"):
            change_member_role(
                database_session,
                actor=admin,
                target=stored_demo,
                new_role="ADMIN",
                occurred_at=datetime(2026, 7, 15, 11, 4, tzinfo=UTC),
            )
        with pytest.raises(MembershipError, match="공개 데모 계정"):
            change_member_status(
                database_session,
                actor=admin,
                target=stored_demo,
                new_status="SUSPENDED",
                occurred_at=datetime(2026, 7, 15, 11, 5, tzinfo=UTC),
            )

        change_member_role(
            database_session,
            actor=admin,
            target=ordinary,
            new_role="ASSISTANT_ADMIN",
            occurred_at=datetime(2026, 7, 15, 11, 6, tzinfo=UTC),
        )
        change_member_status(
            database_session,
            actor=admin,
            target=ordinary,
            new_status="SUSPENDED",
            occurred_at=datetime(2026, 7, 15, 11, 7, tzinfo=UTC),
        )
        database_session.commit()

        database_session.refresh(stored_demo)
        database_session.refresh(ordinary)
        assert (stored_demo.role, stored_demo.status) == ("MEMBER", "ACTIVE")
        assert (ordinary.role, ordinary.status) == ("ASSISTANT_ADMIN", "SUSPENDED")


def test_public_demo_role_pollution_cannot_reach_admin_or_approval_routes(
    postgres_engine: Engine,
) -> None:
    demo = _bootstrap_demo(postgres_engine)
    with Session(postgres_engine) as database_session:
        stored_demo = database_session.get(UserAccount, demo.id)
        assert stored_demo is not None
        stored_demo.role = "ADMIN"
        database_session.commit()

    client = _app(postgres_engine).test_client()
    login = _login(client, "phase11-demo-teacher", "phase11-demo-password")

    assert login.status_code == 302
    assert client.get("/admin/rules").status_code == 403
    assert client.get("/admin/members").status_code == 403
    consultation = client.get("/admin/consultations/new")
    assert consultation.status_code == 302
    assert consultation.headers["Location"].endswith("/calculate?example=1")
    assert login.headers["Location"].endswith("/calculate?example=1")


def test_bootstrap_demo_disabled_revokes_session_and_credentials_then_reactivates_same_actor(
    postgres_engine: Engine,
) -> None:
    demo = _bootstrap_demo(postgres_engine)
    app = _app(postgres_engine)
    client = app.test_client()
    assert _login(client, "phase11-demo-teacher", "phase11-demo-password").status_code == 302
    assert (
        client.get("/admin/consultations/new").headers["Location"].endswith("/calculate?example=1")
    )

    app.config.update(DEMO_LOGIN_NAME=None, DEMO_PUBLIC_PASSWORD=None)
    disabled = app.test_cli_runner().invoke(args=["auth", "bootstrap-demo"])

    assert disabled.exit_code == 0
    assert "기존 공개 데모 계정 전체 해제 완료" in disabled.output
    invalidated = client.get("/admin/consultations/new")
    assert invalidated.status_code == 302
    assert "/auth/login" in invalidated.headers["Location"]
    with Session(postgres_engine) as database_session:
        revoked = database_session.get(UserAccount, demo.id)
        assert revoked is not None
        assert revoked.actor_ref == "demo:public"
        assert (revoked.role, revoked.status) == ("MEMBER", "SUSPENDED")
        assert revoked.login_name == "phase11-demo-teacher"
        assert revoked.password_hash is not None
        assert not check_password_hash(revoked.password_hash, "phase11-demo-password")
        assert revoked.auth_version == demo.auth_version + 1
        assert (
            authenticate_local_member(
                database_session,
                login_name="phase11-demo-teacher",
                password="phase11-demo-password",
                occurred_at=datetime(2026, 7, 15, 11, 8, tzinfo=UTC),
            )
            is None
        )
        audit_types = set(
            database_session.scalars(
                select(UserAccountAuditEvent.event_type).where(
                    UserAccountAuditEvent.target_user_id == demo.id
                )
            )
        )
        assert {"STATUS_CHANGED", "PASSWORD_CHANGED"}.issubset(audit_types)
        revoked_password_hash = revoked.password_hash

    disabled_again = app.test_cli_runner().invoke(args=["auth", "bootstrap-demo"])
    assert disabled_again.exit_code == 0
    with Session(postgres_engine) as database_session:
        still_revoked = database_session.get(UserAccount, demo.id)
        assert still_revoked is not None
        assert still_revoked.auth_version == demo.auth_version + 1
        assert still_revoked.password_hash == revoked_password_hash

    app.config.update(
        DEMO_LOGIN_NAME="phase11-demo-teacher",
        DEMO_PUBLIC_PASSWORD="phase11-rotated-demo-password",
    )
    reactivated = app.test_cli_runner().invoke(args=["auth", "bootstrap-demo"])

    assert reactivated.exit_code == 0
    with Session(postgres_engine) as database_session:
        restored = database_session.get(UserAccount, demo.id)
        assert restored is not None
        assert restored.actor_ref == "demo:public"
        assert (restored.role, restored.status) == ("MEMBER", "SUSPENDED")
        role_demos = tuple(
            database_session.scalars(
                select(UserAccount).where(
                    UserAccount.actor_ref.in_(tuple(DEMO_ROLE_ACTOR_REFS.values()))
                )
            )
        )
        assert len(role_demos) == 4
        assert all(account.status == "ACTIVE" for account in role_demos)

    assert (
        _login(
            app.test_client(),
            DEMO_ROLE_LOGIN_NAMES["STUDENT"],
            "phase11-rotated-demo-password",
        ).status_code
        == 302
    )


def test_bootstrap_demo_incomplete_configuration_fails_closed(
    postgres_engine: Engine,
) -> None:
    _bootstrap_demo(postgres_engine)
    app = _app(postgres_engine)
    app.config.update(DEMO_PUBLIC_PASSWORD=None)

    result = app.test_cli_runner().invoke(args=["auth", "bootstrap-demo"])

    assert result.exit_code != 0
    assert "공개 데모 계정 설정이 불완전합니다." in result.output


@pytest.mark.parametrize(
    ("login_name", "email", "email_account_created"),
    [
        ("phase11-demo-teacher", "reserved-login@phase11.invalid", True),
        ("phase11-reserved-email", "public-demo@local.invalid", False),
    ],
)
def test_email_registration_ignores_legacy_id_tampering_and_reserves_demo_email(
    postgres_engine: Engine,
    login_name: str,
    email: str,
    email_account_created: bool,
) -> None:
    _bootstrap(postgres_engine)
    app = _app(postgres_engine)
    client = app.test_client()
    page = client.get("/auth/register")

    response = client.post(
        "/auth/register",
        data={
            "csrf_token": _csrf(page.get_data(as_text=True)),
            "login_name": login_name,
            "email": email,
            "display_name": "합성 예약값 선점 시도",
            "password": "phase11-member-password",
            "password_confirmation": "phase11-member-password",
        },
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "/auth/registration-received"
    with Session(postgres_engine) as database_session:
        reserved = database_session.scalar(
            select(UserAccount).where(
                (UserAccount.login_name == login_name) | (UserAccount.email == email)
            )
        )
        assert (reserved is not None) is email_account_created
        if reserved is not None:
            assert reserved.login_name is None
            assert reserved.email == email

    bootstrap = app.test_cli_runner().invoke(args=["auth", "bootstrap-demo"])
    assert bootstrap.exit_code == 0
    with Session(postgres_engine) as database_session:
        demos = tuple(
            database_session.scalars(
                select(UserAccount).where(
                    UserAccount.actor_ref.in_(tuple(DEMO_ROLE_ACTOR_REFS.values()))
                )
            )
        )
        assert len(demos) == 4
        assert all(demo.status == "ACTIVE" for demo in demos)


@pytest.mark.parametrize("conflict", ["login", "email"])
def test_bootstrap_demo_conflict_is_nonfatal_and_never_takes_over_an_existing_member(
    postgres_engine: Engine,
    conflict: str,
) -> None:
    with Session(postgres_engine) as database_session:
        admin = bootstrap_admin(
            database_session,
            login_name="phase11-admin",
            password_hash=generate_password_hash("phase11-admin-password"),
            occurred_at=datetime(2026, 7, 15, 11, 9, tzinfo=UTC),
        )
        existing = register_local_member(
            database_session,
            login_name="phase11-preexisting-demo-owner",
            email="preexisting-active@phase11.invalid",
            display_name="기존 활성 합성 회원",
            password="phase11-preexisting-password",
            occurred_at=datetime(2026, 7, 15, 11, 10, tzinfo=UTC),
        )
        approve_pending_member(
            database_session,
            actor=admin,
            target=existing,
            occurred_at=datetime(2026, 7, 15, 11, 11, tzinfo=UTC),
        )
        if conflict == "login":
            # 데모 식별자 예약 기능 배포 전에 생성된 계정을 합성한다.
            existing.login_name = DEMO_ROLE_LOGIN_NAMES["STUDENT"]
        else:
            # 데모 식별자 예약 기능 배포 전에 생성된 계정을 합성한다.
            existing.email = "public-demo-student@local.invalid"
        database_session.commit()
        existing_id = existing.id
        existing_login = existing.login_name
        existing_email = existing.email

    app = _app(postgres_engine)
    result = app.test_cli_runner().invoke(args=["auth", "bootstrap-demo"])

    assert result.exit_code == 0
    assert "데모 전체를 비활성 상태로 유지합니다." in result.output
    login_body = app.test_client().get("/auth/login").get_data(as_text=True)
    assert "포트폴리오 공개 체험 계정" not in login_body
    assert "phase11-demo-password" not in login_body
    with Session(postgres_engine) as database_session:
        preserved = database_session.get(UserAccount, existing_id)
        assert preserved is not None
        assert preserved.actor_ref not in DEMO_ROLE_ACTOR_REFS.values()
        assert (preserved.role, preserved.status) == ("MEMBER", "ACTIVE")
        assert (preserved.login_name, preserved.email) == (existing_login, existing_email)
        assert not tuple(
            database_session.scalars(
                select(UserAccount).where(
                    UserAccount.actor_ref.in_(tuple(DEMO_ROLE_ACTOR_REFS.values())),
                    UserAccount.status == "ACTIVE",
                )
            )
        )


def test_bootstrap_ignores_legacy_login_rotation_and_replaces_old_demo_with_fixed_roles(
    postgres_engine: Engine,
) -> None:
    demo = _bootstrap_demo(postgres_engine)
    with Session(postgres_engine) as database_session:
        owner = register_local_member(
            database_session,
            login_name="phase11-rotated-demo-login",
            email="rotated-demo-owner@phase11.invalid",
            display_name="합성 회전 로그인 소유자",
            password="phase11-existing-owner-password",
            occurred_at=datetime(2026, 7, 15, 11, 12, tzinfo=UTC),
        )
        database_session.commit()
        owner_id = owner.id

    app = _app(postgres_engine)
    client = app.test_client()
    assert _login(client, "phase11-demo-teacher", "phase11-demo-password").status_code == 302
    assert (
        client.get("/admin/consultations/new").headers["Location"].endswith("/calculate?example=1")
    )
    app.config.update(
        DEMO_LOGIN_NAME="phase11-rotated-demo-login",
        DEMO_PUBLIC_PASSWORD="phase11-rotated-demo-password",
    )

    result = app.test_cli_runner().invoke(args=["auth", "bootstrap-demo"])

    assert result.exit_code == 0
    assert "공개 네 역할 데모 계정 부트스트랩 확인 완료" in result.output
    invalidated = client.get("/admin/consultations/new")
    assert invalidated.status_code == 302
    assert "/auth/login" in invalidated.headers["Location"]
    login_body = app.test_client().get("/auth/login").get_data(as_text=True)
    assert "포트폴리오 공개 체험 계정" in login_body
    assert "phase11-rotated-demo-login" not in login_body
    assert "phase11-rotated-demo-password" in login_body
    for fixed_login in DEMO_ROLE_LOGIN_NAMES.values():
        assert fixed_login in login_body
    with Session(postgres_engine) as database_session:
        preserved = database_session.get(UserAccount, owner_id)
        revoked = database_session.get(UserAccount, demo.id)
        assert preserved is not None and revoked is not None
        assert preserved.actor_ref != "demo:public"
        assert (preserved.role, preserved.status) == ("MEMBER", "PENDING_APPROVAL")
        assert (revoked.role, revoked.status) == ("MEMBER", "SUSPENDED")
        assert revoked.auth_version == demo.auth_version + 1
        assert revoked.password_hash is not None
        assert not check_password_hash(revoked.password_hash, "phase11-demo-password")
        assert (
            len(
                tuple(
                    database_session.scalars(
                        select(UserAccount).where(
                            UserAccount.actor_ref.in_(tuple(DEMO_ROLE_ACTOR_REFS.values())),
                            UserAccount.status == "ACTIVE",
                        )
                    )
                )
            )
            == 4
        )


def test_bootstrap_retires_legacy_demo_that_owns_a_fixed_role_login(
    postgres_engine: Engine,
) -> None:
    demo = _bootstrap_demo(postgres_engine)
    with Session(postgres_engine) as database_session:
        legacy = database_session.get(UserAccount, demo.id)
        assert legacy is not None
        legacy.login_name = DEMO_ROLE_LOGIN_NAMES["TEACHER"]
        legacy.password_hash = generate_password_hash("phase11-demo-password")
        database_session.commit()

    app = _app(postgres_engine)
    result = app.test_cli_runner().invoke(args=["auth", "bootstrap-demo"])

    assert result.exit_code == 0
    assert "공개 네 역할 데모 계정 부트스트랩 확인 완료" in result.output
    with Session(postgres_engine) as database_session:
        retired = database_session.get(UserAccount, demo.id)
        assert retired is not None
        assert retired.actor_ref == "demo:public"
        assert (retired.role, retired.status) == ("MEMBER", "SUSPENDED")
        assert retired.login_name == f"retired-demo-{retired.id}"
        assert retired.password_hash is not None
        assert not check_password_hash(retired.password_hash, "phase11-demo-password")
        role_demos = tuple(
            database_session.scalars(
                select(UserAccount).where(
                    UserAccount.actor_ref.in_(tuple(DEMO_ROLE_ACTOR_REFS.values()))
                )
            )
        )
        assert len(role_demos) == 4
        assert all(account.status == "ACTIVE" for account in role_demos)
        assert {account.login_name for account in role_demos} == set(DEMO_ROLE_LOGIN_NAMES.values())


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
                select(UserAccount).where(UserAccount.email == "duplicate@phase11.invalid")
            )
        )
        assert len(members) == 1
        assert members[0].login_name is None


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
    assert member_login.headers["Location"].endswith("/dashboard")
    consultation = client.get("/admin/consultations/new")
    assert consultation.status_code == 200
    consultation_body = consultation.get_data(as_text=True)
    assert "지원자격" in consultation_body
    assert "가상 미래전문대" not in consultation_body
    assert "합성 데이터 전용 체험" not in consultation_body


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


def test_active_local_account_explicitly_links_and_unlinks_matching_google_identity(
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine) as database_session:
        admin = _bootstrap(postgres_engine)
        member = register_local_member(
            database_session,
            login_name="phase11-google-link-member",
            email="google@phase11.invalid",
            display_name="합성 Google 연결 회원",
            password="phase11-google-link-password",
            occurred_at=datetime(2026, 7, 15, 10, 30, tzinfo=UTC),
        )
        member.email_verified_at = datetime(2026, 7, 15, 10, 31, tzinfo=UTC)
        approve_pending_member(
            database_session,
            actor=admin,
            target=member,
            occurred_at=datetime(2026, 7, 15, 10, 32, tzinfo=UTC),
        )
        database_session.commit()
        member_id = member.id

    app = _oidc_app(postgres_engine)
    app.extensions["google_oidc_client"] = _SyntheticGoogleClient()
    client = app.test_client()
    assert (
        _login(client, "phase11-google-link-member", "phase11-google-link-password").status_code
        == 302
    )

    security_page = client.get("/account/security")
    connect = client.post(
        "/account/security/google/connect",
        data={
            "csrf_token": _csrf(security_page.get_data(as_text=True)),
            "current_password": "phase11-google-link-password",
        },
    )
    assert connect.status_code == 303
    assert connect.headers["Location"].endswith("/auth/google/start?intent=link")

    callback = client.get("/auth/google/callback?code=link&state=synthetic")
    assert callback.status_code == 303
    assert callback.headers["Location"].endswith("/account/security?message=google_connected")
    with Session(postgres_engine) as database_session:
        identity = database_session.scalar(
            select(ExternalIdentity).where(ExternalIdentity.user_account_id == member_id)
        )
        assert identity is not None
        assert identity.provider_subject == "phase11-google-subject"

    linked_page = client.get("/account/security")
    failed_unlink = client.post(
        "/account/security/google/disconnect",
        data={
            "csrf_token": _csrf(linked_page.get_data(as_text=True)),
            "current_password": "wrong-password",
        },
    )
    assert failed_unlink.status_code == 400
    successful_unlink = client.post(
        "/account/security/google/disconnect",
        data={
            "csrf_token": _csrf(failed_unlink.get_data(as_text=True)),
            "current_password": "phase11-google-link-password",
        },
    )
    assert successful_unlink.status_code == 303
    with Session(postgres_engine) as database_session:
        assert (
            database_session.scalar(
                select(ExternalIdentity).where(ExternalIdentity.user_account_id == member_id)
            )
            is None
        )


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
    _set_google_login_intent(client)
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
    _set_google_login_intent(first_client)

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
    _set_google_login_intent(second_client)
    second = second_client.get("/auth/google/callback?code=second&state=second")

    assert second.status_code == 302
    assert second.headers["Location"].endswith("/dashboard")
    with Session(postgres_engine) as database_session:
        accounts = tuple(
            database_session.scalars(
                select(UserAccount).where(UserAccount.email == "google@phase11.invalid")
            )
        )
        assert len(accounts) == 1
        assert accounts[0].id == member_id
        assert accounts[0].last_login_at is not None
