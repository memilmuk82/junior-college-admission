from __future__ import annotations

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


def test_production_rejects_nonempty_but_invalid_admin_hash() -> None:
    config = _production_config()
    config["ADMIN_PASSWORD_HASH"] = "scrypt:not-a-valid-hash"

    with pytest.raises(RuntimeError, match="ADMIN_PASSWORD_HASH"):
        create_app(config)


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
