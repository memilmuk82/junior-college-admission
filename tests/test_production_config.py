from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

from app import create_app


def _production_config() -> dict[str, object]:
    return {
        "APP_ENV": "production",
        "SECRET_KEY": "synthetic-production-secret-that-is-long-enough",
        "DATABASE_URL": "postgresql+psycopg://synthetic:synthetic@db:5432/synthetic",
        "ADMIN_USERNAME": "synthetic-admin",
        "ADMIN_PASSWORD_HASH": generate_password_hash("synthetic-password"),
        "BYOK_MASTER_KEY": Fernet.generate_key().decode(),
        "PUBLIC_BASE_URL": "https://service.example.test",
        "TRUSTED_HOSTS": ["service.example.test"],
        "TRUST_PROXY_HOPS": 1,
        "TESTING": True,
    }


def test_production_rejects_missing_or_development_configuration() -> None:
    with pytest.raises(RuntimeError) as caught:
        create_app(
            {
                "APP_ENV": "production",
                "SECRET_KEY": "development-only-change-me",
                "DATABASE_URL": "sqlite:///unsafe.db",
                "TRUSTED_HOSTS": [],
                "TRUST_PROXY_HOPS": 0,
                "TESTING": True,
            }
        )

    message = str(caught.value)
    for variable_name in (
        "SECRET_KEY",
        "DATABASE_URL",
        "ADMIN_USERNAME",
        "ADMIN_PASSWORD_HASH",
        "BYOK_MASTER_KEY",
        "PUBLIC_BASE_URL",
        "TRUSTED_HOSTS",
        "TRUST_PROXY_HOPS",
    ):
        assert variable_name in message
    assert "unsafe.db" not in message


def test_production_enables_secure_cookie_and_single_proxy_hop() -> None:
    app = create_app(_production_config())

    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
    assert app.config["PREFERRED_URL_SCHEME"] == "https"
    assert isinstance(app.wsgi_app, ProxyFix)

    response = app.test_client().get("/health", base_url="https://service.example.test")
    assert response.headers["Strict-Transport-Security"] == ("max-age=31536000; includeSubDomains")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Frame-Options"] == "DENY"


def test_production_rejects_nonempty_but_invalid_admin_hash() -> None:
    config = _production_config()
    config["ADMIN_PASSWORD_HASH"] = "scrypt:not-a-valid-hash"

    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD_HASH"):
        create_app(config)


def test_production_reads_secrets_from_bounded_single_line_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    values = {
        "SECRET_KEY": "synthetic-production-secret-that-is-long-enough",
        "DATABASE_URL": "postgresql+psycopg://synthetic:synthetic@db:5432/synthetic",
        "ADMIN_USERNAME": "synthetic-admin",
        "ADMIN_PASSWORD_HASH": generate_password_hash("synthetic-password"),
        "BYOK_MASTER_KEY": Fernet.generate_key().decode(),
    }
    for name, value in values.items():
        secret_file = tmp_path / name.lower()
        secret_file.write_text(f"{value}\n", encoding="utf-8")
        monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv(f"{name}_FILE", str(secret_file))
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://service.example.test")
    monkeypatch.setenv("TRUSTED_HOSTS", "service.example.test")
    monkeypatch.setenv("TRUST_PROXY_HOPS", "1")

    app = create_app({"TESTING": True})

    assert app.config["SECRET_KEY"] == values["SECRET_KEY"]
    assert app.config["DATABASE_URL"] == values["DATABASE_URL"]
    assert app.config["ADMIN_PASSWORD_HASH"] == values["ADMIN_PASSWORD_HASH"]


def test_secret_rejects_direct_and_file_input_conflict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    secret_file = tmp_path / "secret_key"
    secret_file.write_text("synthetic-file-secret", encoding="utf-8")
    monkeypatch.setenv("SECRET_KEY", "synthetic-direct-secret")
    monkeypatch.setenv("SECRET_KEY_FILE", str(secret_file))

    with pytest.raises(RuntimeError) as caught:
        create_app({"TESTING": True})

    assert "SECRET_KEY" in str(caught.value)
    assert "synthetic" not in str(caught.value)


@pytest.mark.parametrize("content", ["", "first\nsecond", "x" * (64 * 1024 + 1)])
def test_secret_file_rejects_empty_multiline_and_oversized_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str
) -> None:
    secret_file = tmp_path / "secret_key"
    secret_file.write_text(content, encoding="utf-8")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY_FILE", str(secret_file))

    with pytest.raises(RuntimeError, match="SECRET_KEY_FILE"):
        create_app({"TESTING": True})


def test_production_trusted_hosts_reject_unconfigured_host() -> None:
    app = create_app(_production_config())
    client = app.test_client()

    assert client.get("/health", base_url="https://service.example.test").status_code == 200
    assert client.get("/health", base_url="https://untrusted.example.test").status_code == 400


@pytest.mark.parametrize(
    "public_base_url",
    [
        "http://service.example.test",
        "https://untrusted.example.test",
        "https://service.example.test/path",
        "https://service.example.test?secret=value",
    ],
)
def test_production_requires_https_base_url_for_a_trusted_host(
    public_base_url: str,
) -> None:
    config = _production_config()
    config["PUBLIC_BASE_URL"] = public_base_url

    with pytest.raises(RuntimeError, match="PUBLIC_BASE_URL"):
        create_app(config)


@pytest.mark.parametrize("proxy_hops", [-1, 0, 2, "one"])
def test_production_requires_exactly_one_trusted_proxy_hop(proxy_hops: object) -> None:
    config = _production_config()
    config["TRUST_PROXY_HOPS"] = proxy_hops

    with pytest.raises(RuntimeError, match="TRUST_PROXY_HOPS"):
        create_app(config)


def test_default_compose_origin_port_is_loopback_only() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert '      - "127.0.0.1:8000:8000"' in compose
    assert '      - "0.0.0.0:8000:8000"' not in compose


def test_host_nginx_production_override_exposes_only_gunicorn_on_loopback() -> None:
    compose = Path("docker-compose.host-nginx.yml").read_text(encoding="utf-8")

    assert "name: junior-college-admission-live" in compose
    assert '"127.0.0.1:${PRODUCTION_ORIGIN_PORT:-8000}:5000"' in compose
    assert 'profiles: ["container-tls"]' in compose
