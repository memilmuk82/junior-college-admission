from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import Engine, delete, or_, select
from sqlalchemy.orm import Session

from app import create_app
from app.models import AccountAuthToken, ExternalIdentity, UserAccount, UserAccountAuditEvent
from app.services.demo_sandbox import reset_demo_role_accounts

INSTANCE_ID = "route-v1"
PUBLIC_PASSWORD = "synthetic-public-password"


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _cleanup(engine: Engine) -> None:
    with Session(engine) as database_session:
        account_ids = tuple(
            database_session.scalars(
                select(UserAccount.id).where(UserAccount.actor_ref.like(f"sandbox:{INSTANCE_ID}:%"))
            )
        )
        if account_ids:
            database_session.execute(
                delete(UserAccountAuditEvent).where(
                    or_(
                        UserAccountAuditEvent.target_user_id.in_(account_ids),
                        UserAccountAuditEvent.actor_user_id.in_(account_ids),
                    )
                )
            )
            database_session.execute(
                delete(AccountAuthToken).where(AccountAuthToken.user_account_id.in_(account_ids))
            )
            database_session.execute(
                delete(ExternalIdentity).where(ExternalIdentity.user_account_id.in_(account_ids))
            )
            database_session.execute(delete(UserAccount).where(UserAccount.id.in_(account_ids)))
        database_session.commit()


@pytest.fixture
def sandbox_app(postgres_engine: Engine) -> Iterator[Flask]:
    _cleanup(postgres_engine)
    config: dict[str, object] = {
        "TESTING": True,
        "SECRET_KEY": "phase20-sandbox-route-secret",
        "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
        "BYOK_MASTER_KEY": Fernet.generate_key().decode("ascii"),
        "PUBLIC_BASE_URL": "https://phase20.example.invalid",
        "EMAIL_FROM_ADDRESS": "demo@phase20.example.invalid",
        "DEMO_SANDBOX_ENABLED": True,
        "DEMO_SANDBOX_INSTANCE_ID": INSTANCE_ID,
        "DEMO_SANDBOX_PUBLIC_PASSWORD": PUBLIC_PASSWORD,
        "DEMO_EMAIL_OUTBOX_ENABLED": True,
        "DEMO_GOOGLE_STUB_ENABLED": True,
        "DEMO_CRAWLER_FIXTURE_ENABLED": True,
        "GOOGLE_OIDC_ENABLED": False,
        "ALLOW_LEGACY_ADMIN_LOGIN": False,
    }
    app = create_app(config)
    with Session(postgres_engine) as database_session:
        reset_demo_role_accounts(
            database_session,
            config=app.config,
            occurred_at=datetime(2026, 7, 20, 23, 0, tzinfo=UTC),
        )
        database_session.commit()
    yield app
    _cleanup(postgres_engine)


def _start_role(client: FlaskClient, role: str) -> None:
    page = client.get("/auth/login")
    response = client.post(
        f"/auth/demo-start/{role}",
        data={"csrf_token": _csrf(page.get_data(as_text=True))},
    )
    assert response.status_code == 303
    assert response.headers["Location"].endswith("/dashboard")


def test_sandbox_one_click_login_allows_password_change_and_fixed_gateway_recovery(
    sandbox_app: Flask,
) -> None:
    client = sandbox_app.test_client()
    login_page = client.get("/auth/login")
    body = login_page.get_data(as_text=True)
    assert "전체 기능 체험 계정" in body
    assert "학생 기능 체험 시작" in body

    _start_role(client, "student")
    security = client.get("/account/security")
    security_body = security.get_data(as_text=True)
    assert security.status_code == 200
    assert "격리 체험 계정 보안" in security_body
    changed = client.post(
        "/account/security/password",
        data={
            "csrf_token": _csrf(security_body),
            "current_password": PUBLIC_PASSWORD,
            "new_password": "visitor-updated-password",
            "new_password_confirmation": "visitor-updated-password",
        },
    )
    assert changed.status_code == 303

    logout_page = client.get("/dashboard")
    assert (
        client.post(
            "/auth/logout",
            data={"csrf_token": _csrf(logout_page.get_data(as_text=True))},
        ).status_code
        == 302
    )
    _start_role(client, "student")
    assert client.get("/dashboard").status_code == 200


def test_sandbox_google_stub_runs_existing_link_callback_and_disconnect_flow(
    sandbox_app: Flask,
    postgres_engine: Engine,
) -> None:
    client = sandbox_app.test_client()
    _start_role(client, "teacher")
    security = client.get("/account/security")
    connect = client.post(
        "/account/security/google/connect",
        data={
            "csrf_token": _csrf(security.get_data(as_text=True)),
            "current_password": PUBLIC_PASSWORD,
        },
    )
    assert connect.status_code == 303
    start = client.get(connect.headers["Location"])
    assert start.status_code == 303
    assert start.headers["Location"].endswith("/auth/google/demo-consent")
    consent = client.get(start.headers["Location"])
    consent_body = consent.get_data(as_text=True)
    assert "실제 Google 계정은 사용하지 않습니다" in consent_body
    approved = client.post(
        "/auth/google/demo-consent",
        data={
            "csrf_token": _csrf(consent_body),
            "email": "public-demo-teacher@local.invalid",
            "display_name": "체험 교사 Google",
        },
    )
    assert approved.status_code == 303
    callback = client.get(approved.headers["Location"])
    assert callback.status_code == 303
    assert "google_connected" in callback.headers["Location"]

    with Session(postgres_engine) as database_session:
        teacher = database_session.scalar(
            select(UserAccount).where(
                UserAccount.actor_ref == f"sandbox:{INSTANCE_ID}:role:TEACHER"
            )
        )
        assert teacher is not None
        assert (
            database_session.scalar(
                select(ExternalIdentity).where(ExternalIdentity.user_account_id == teacher.id)
            )
            is not None
        )

    security = client.get(callback.headers["Location"])
    disconnected = client.post(
        "/account/security/google/disconnect",
        data={
            "csrf_token": _csrf(security.get_data(as_text=True)),
            "current_password": PUBLIC_PASSWORD,
        },
    )
    assert disconnected.status_code == 303


def test_same_demo_role_can_start_in_two_browsers_without_revoking_first_session(
    sandbox_app: Flask,
) -> None:
    first_browser = sandbox_app.test_client()
    second_browser = sandbox_app.test_client()

    _start_role(first_browser, "student")
    _start_role(second_browser, "student")

    first_dashboard = first_browser.get("/dashboard")
    second_dashboard = second_browser.get("/dashboard")
    assert first_dashboard.status_code == 200
    assert second_dashboard.status_code == 200
    assert "학생 업무공간" in first_dashboard.get_data(as_text=True)


def test_sandbox_assistant_is_limited_to_account_approval(
    sandbox_app: Flask,
) -> None:
    client = sandbox_app.test_client()
    _start_role(client, "assistant_admin")

    dashboard = client.get("/dashboard")
    body = dashboard.get_data(as_text=True)
    assert dashboard.status_code == 200
    assert "보조 관리자 승인 업무" in body
    assert 'href="/admin/members"' in body
    assert 'href="/teacher/classrooms"' not in body
    assert 'href="/teacher/outcomes"' not in body
    assert 'href="/account/records"' not in body
    assert 'href="/admin/ai/settings"' not in body
    assert client.get("/admin/members").status_code == 200
    assert client.get("/account/security").status_code == 200

    for path in (
        "/teacher/classrooms",
        "/teacher/outcomes",
        "/account/records",
        "/admin/consultations/new",
        "/admin/ai/settings",
    ):
        assert client.get(path).status_code == 403
    assert client.post("/admin/ai/credentials", data={}).status_code == 403
