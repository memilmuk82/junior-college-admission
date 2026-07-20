from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from flask import render_template, session, url_for

from app import create_app
from app.auth import post_login_destination
from app.models import UserAccount
from app.services.account_emails import account_email_available, send_email_verification

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _sandbox_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "APP_ENV": "demo-sandbox",
        "TESTING": True,
        "SECRET_KEY": "synthetic-demo-sandbox-secret-long-enough",
        "DATABASE_URL": "postgresql+psycopg://demo:demo@db-demo:5432/demo",
        "BYOK_MASTER_KEY": Fernet.generate_key().decode("ascii"),
        "PUBLIC_BASE_URL": "https://service.example.test/demo",
        "TRUSTED_HOSTS": ["service.example.test"],
        "TRUST_PROXY_HOPS": 1,
        "APPLICATION_ROOT": "/demo",
        "SESSION_COOKIE_NAME": "admission_demo_session",
        "SESSION_COOKIE_PATH": "/demo",
        "DEMO_SANDBOX_ENABLED": True,
        "DEMO_SANDBOX_INSTANCE_ID": "synthetic-demo",
        "DEMO_PUBLIC_PASSWORD": "synthetic-demo-password",
        "DEMO_EMAIL_OUTBOX_ENABLED": True,
        "DEMO_GOOGLE_STUB_ENABLED": True,
        "DEMO_CRAWLER_FIXTURE_ENABLED": True,
        "GOOGLE_OIDC_ENABLED": False,
        "EMAIL_FROM_ADDRESS": "demo-accounts@service.example.test",
    }
    config.update(overrides)
    return config


def test_demo_sandbox_deployment_uses_prefix_cookie_and_outbox_without_external_secrets() -> None:
    app = create_app(_sandbox_config())

    @app.get("/phase20-prefix-probe")
    def phase20_prefix_probe():  # type: ignore[no-untyped-def]
        session["probe"] = "ok"
        return {"health_url": url_for("main.health")}

    response = app.test_client().get(
        "/phase20-prefix-probe",
        base_url="https://service.example.test",
        headers={"X-Forwarded-Prefix": "/demo"},
    )

    assert response.status_code == 200
    assert response.json == {"health_url": "/demo/health"}
    assert "admission_demo_session=" in response.headers["Set-Cookie"]
    assert "Path=/demo" in response.headers["Set-Cookie"]
    assert "Secure" in response.headers["Set-Cookie"]
    assert app.config["ACCOUNT_EMAIL_ENABLED"] is True
    assert app.config["ACCOUNT_EMAIL_OUTBOX"] == []
    assert app.config["SMTP_PASSWORD"] is None
    assert app.config["GOOGLE_OIDC_CLIENT_SECRET"] is None


def test_demo_outbox_links_keep_the_application_prefix() -> None:
    outbox: list[EmailMessage] = []
    app = create_app(_sandbox_config(ACCOUNT_EMAIL_OUTBOX=outbox))

    with app.app_context():
        assert account_email_available() is True
        send_email_verification(
            recipient="student@example.invalid",
            raw_token="synthetic-demo-token",
        )

    assert len(outbox) == 1
    assert (
        "https://service.example.test/demo/auth/email/verify?token=synthetic-demo-token"
        in outbox[0].get_content()
    )


def test_demo_landing_links_do_not_escape_the_application_prefix() -> None:
    app = create_app(_sandbox_config())

    @app.get("/phase20-landing-probe")
    def phase20_landing_probe():  # type: ignore[no-untyped-def]
        return render_template("index.html", current_user=None)

    response = app.test_client().get(
        "/phase20-landing-probe",
        base_url="https://service.example.test",
        headers={"X-Forwarded-Prefix": "/demo"},
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'href="/demo/"' in body
    assert "next=/demo/account/records" in body
    assert 'href="/"' not in body


def test_demo_post_login_destination_rejects_prefixless_next_path() -> None:
    app = create_app(_sandbox_config())
    user = UserAccount(actor_ref="sandbox:synthetic-demo:role:STUDENT")

    with app.test_request_context("/", base_url="https://service.example.test/demo/"):
        assert post_login_destination(user, "/account/records") == "/demo/dashboard"
        assert post_login_destination(user, "/demo/account/records") == "/demo/account/records"


@pytest.mark.parametrize(
    ("override", "missing_name"),
    (
        ({"DEMO_SANDBOX_ENABLED": False}, "DEMO_SANDBOX_ENABLED"),
        ({"DEMO_SANDBOX_INSTANCE_ID": ""}, "DEMO_SANDBOX_INSTANCE_ID"),
        ({"DEMO_GOOGLE_STUB_ENABLED": False}, "DEMO_GOOGLE_STUB_ENABLED"),
        ({"DEMO_EMAIL_OUTBOX_ENABLED": False}, "DEMO_EMAIL_OUTBOX_ENABLED"),
        ({"DEMO_CRAWLER_FIXTURE_ENABLED": False}, "DEMO_CRAWLER_FIXTURE_ENABLED"),
        ({"SESSION_COOKIE_NAME": "session"}, "SESSION_COOKIE_NAME"),
        ({"SESSION_COOKIE_PATH": "/"}, "SESSION_COOKIE_PATH"),
        ({"PUBLIC_BASE_URL": "https://service.example.test"}, "PUBLIC_BASE_URL"),
    ),
)
def test_demo_sandbox_deployment_fails_closed_when_isolation_contract_is_incomplete(
    override: dict[str, object], missing_name: str
) -> None:
    with pytest.raises(RuntimeError, match=missing_name):
        create_app(_sandbox_config(**override))


def test_production_cannot_enable_demo_side_effect_stubs() -> None:
    config = _sandbox_config(
        APP_ENV="production",
        ADMIN_USERNAME="synthetic-admin",
        ADMIN_PASSWORD_HASH=(
            "scrypt:32768:8:1$syntheticSalt$"
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        ),
    )

    with pytest.raises(RuntimeError, match="DEMO_SANDBOX_ENABLED"):
        create_app(config)


def test_demo_compose_keeps_application_and_database_on_an_internal_network() -> None:
    compose = (REPOSITORY_ROOT / "docker-compose.demo.yml").read_text(encoding="utf-8")
    web_section = compose.split("  web-demo:", 1)[1].split("  gateway-demo:", 1)[0]
    gateway_section = compose.split("  gateway-demo:", 1)[1].split("  db-demo:", 1)[0]

    assert "db-demo:5432" not in compose
    assert "demo_database_url" in web_section
    assert "production" not in web_section.lower()
    assert 'expose:\n      - "5000"' in web_section
    assert "ports:" not in web_section
    assert "127.0.0.1:${DEMO_ORIGIN_PORT:-8002}:8080" in gateway_section
    assert "demo-backend:\n    driver: bridge\n    internal: true" in compose
    assert "junior-college-admission-demo-postgres-data" in compose
    assert "production_postgres_data" not in compose


def test_demo_image_contains_its_startup_guard_without_a_host_script_mount() -> None:
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
    compose = (REPOSITORY_ROOT / "docker-compose.demo.yml").read_text(encoding="utf-8")
    runtime = (REPOSITORY_ROOT / "scripts/run_demo_web.sh").read_text(encoding="utf-8")

    assert "scripts/run_demo_web.sh ./scripts/" in dockerfile
    assert "./scripts/run_demo_web.sh:/app/scripts/run_demo_web.sh" not in compose
    assert 'APP_ENV:-}" != "demo-sandbox"' in runtime
    assert "@db-demo:5432/" in runtime
    assert "demo-sandbox purge-session-ai" in runtime
