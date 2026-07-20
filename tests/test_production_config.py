from __future__ import annotations

import re
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
        "GOOGLE_OIDC_ENABLED": False,
        "ACCOUNT_EMAIL_ENABLED": False,
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


def test_production_google_oidc_is_opt_in_and_fails_closed_without_credentials() -> None:
    config = _production_config()
    config["GOOGLE_OIDC_ENABLED"] = True

    with pytest.raises(RuntimeError) as caught:
        create_app(config)

    assert "GOOGLE_OIDC_CLIENT_ID" in str(caught.value)
    assert "GOOGLE_OIDC_CLIENT_SECRET" in str(caught.value)


def test_production_google_oidc_requires_exact_trusted_https_callback() -> None:
    config = _production_config() | {
        "GOOGLE_OIDC_ENABLED": True,
        "GOOGLE_OIDC_CLIENT_ID": "synthetic-client-id",
        "GOOGLE_OIDC_CLIENT_SECRET": "synthetic-client-secret",
        "GOOGLE_REDIRECT_URI": "https://service.example.test/auth/google/callback",
    }

    app = create_app(config)
    assert app.extensions["google_oidc_client"] is not None

    config["GOOGLE_REDIRECT_URI"] = "https://untrusted.example.test/auth/google/callback"
    with pytest.raises(RuntimeError, match="GOOGLE_REDIRECT_URI"):
        create_app(config)


def test_production_account_email_is_opt_in_and_fails_closed_without_smtp() -> None:
    config = _production_config()
    config["ACCOUNT_EMAIL_ENABLED"] = True

    with pytest.raises(RuntimeError) as caught:
        create_app(config)

    for variable_name in (
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "EMAIL_FROM_ADDRESS",
    ):
        assert variable_name in str(caught.value)


def test_production_account_email_requires_starttls_and_bounded_transport() -> None:
    config = _production_config() | {
        "ACCOUNT_EMAIL_ENABLED": True,
        "SMTP_HOST": "smtp.example.test",
        "SMTP_PORT": "587",
        "SMTP_USERNAME": "synthetic-user",
        "SMTP_PASSWORD": "synthetic-secret",
        "SMTP_USE_STARTTLS": True,
        "EMAIL_FROM_ADDRESS": "accounts@service.example.test",
        "SMTP_TIMEOUT_SECONDS": "5",
    }

    app = create_app(config)
    assert app.config["ACCOUNT_EMAIL_ENABLED"] is True

    config["SMTP_USE_STARTTLS"] = False
    config["SMTP_PORT"] = "587.5"
    config["SMTP_TIMEOUT_SECONDS"] = "31"
    with pytest.raises(RuntimeError) as caught:
        create_app(config)
    assert "SMTP_USE_STARTTLS" in str(caught.value)
    assert "SMTP_PORT" in str(caught.value)
    assert "SMTP_TIMEOUT_SECONDS" in str(caught.value)


def test_production_account_email_reads_credentials_from_secret_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    username_file = tmp_path / "smtp_username"
    password_file = tmp_path / "smtp_password"
    username_file.write_text("synthetic-smtp-user\n", encoding="utf-8")
    password_file.write_text("synthetic-smtp-password\n", encoding="utf-8")
    monkeypatch.delenv("SMTP_USERNAME", raising=False)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.setenv("SMTP_USERNAME_FILE", str(username_file))
    monkeypatch.setenv("SMTP_PASSWORD_FILE", str(password_file))

    config = _production_config() | {
        "ACCOUNT_EMAIL_ENABLED": True,
        "SMTP_HOST": "smtp.example.test",
        "SMTP_PORT": "587",
        "SMTP_USE_STARTTLS": True,
        "EMAIL_FROM_ADDRESS": "accounts@service.example.test",
        "SMTP_TIMEOUT_SECONDS": "5",
    }
    app = create_app(config)

    assert app.config["SMTP_USERNAME"] == "synthetic-smtp-user"
    assert app.config["SMTP_PASSWORD"] == "synthetic-smtp-password"


def test_default_compose_origin_port_is_loopback_only() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert '      - "127.0.0.1:8000:8000"' in compose
    assert '      - "0.0.0.0:8000:8000"' not in compose


def test_host_nginx_production_override_exposes_only_gunicorn_on_loopback() -> None:
    compose = Path("docker-compose.host-nginx.yml").read_text(encoding="utf-8")

    assert "name: junior-college-admission-live" in compose
    assert '"127.0.0.1:${PRODUCTION_ORIGIN_PORT:-8000}:5000"' in compose
    assert 'profiles: ["container-tls"]' in compose


def test_origin_rollback_requires_restored_database_and_immutable_image() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    target = makefile.split("production-origin-rollback-app:", 1)[1].split(
        "\nproduction-origin-backup:", 1
    )[0]

    assert 'ROLLBACK_DATABASE_RESTORE_CONFIRMED)" = "RESTORED_AND_VERIFIED"' in target
    assert "docker image inspect --format '{{.Id}}'" in target
    assert 'test "$$actual_id" = "$(ROLLBACK_APP_IMAGE_ID)"' in target
    assert "PRODUCTION_BOOTSTRAP_ADMIN_ON_STARTUP=0" in target
    assert "--no-build --no-deps --wait web-production" in target
    assert "--build" not in target


def test_production_compose_runs_app_as_secret_owner_and_initializes_upload_volume() -> None:
    compose = Path("docker-compose.production.yml").read_text(encoding="utf-8")

    assert 'user: "${PRODUCTION_APP_UID:?PRODUCTION_APP_UID must be set}' in compose
    assert "init-production-uploads:" in compose
    assert "condition: service_completed_successfully" in compose
    assert "- CHOWN" in compose
    assert "- FOWNER" in compose
    assert "cap_drop:\n      - ALL" in compose


def test_runtime_profiles_bootstrap_database_admin_before_serving() -> None:
    for compose_file in (
        "docker-compose.alpha.yml",
        "docker-compose.beta.yml",
        "docker-compose.production.yml",
    ):
        compose = Path(compose_file).read_text(encoding="utf-8")
        runtime = (
            Path("scripts/run_production_web.sh").read_text(encoding="utf-8")
            if compose_file == "docker-compose.production.yml"
            else compose
        )
        migration = runtime.index("flask --app wsgi db upgrade")
        bootstrap = runtime.index("flask --app wsgi auth bootstrap-admin")
        server = runtime.index("gunicorn", bootstrap)

        assert migration < bootstrap < server

    production = Path("scripts/run_production_web.sh").read_text(encoding="utf-8")
    assert 'case "${PRODUCTION_BOOTSTRAP_ADMIN_ON_STARTUP:-1}" in' in production


def test_runtime_profiles_use_query_free_gunicorn_access_logs() -> None:
    safe_format = "--access-logformat='%(t)s \"%(m)s %(U)s %(H)s\" %(s)s %(b)s'"
    for compose_file in (
        "docker-compose.alpha.yml",
        "docker-compose.beta.yml",
        "docker-compose.production.yml",
    ):
        compose = Path(compose_file).read_text(encoding="utf-8")
        runtime = (
            Path("scripts/run_production_web.sh").read_text(encoding="utf-8")
            if compose_file == "docker-compose.production.yml"
            else compose
        )

        assert safe_format in runtime
        assert "%(r)s" not in runtime
        assert "%(q)s" not in runtime
        assert "%(f)s" not in runtime

    alpha = Path("docker-compose.alpha.yml").read_text(encoding="utf-8")
    assert "flask --app wsgi run" not in alpha


def test_production_nginx_access_log_excludes_query_and_referrer() -> None:
    nginx = Path("deploy/nginx.production.conf").read_text(encoding="utf-8")
    match = re.search(r"log_format path_only (?P<format>.*?);", nginx, re.DOTALL)

    assert match is not None
    access_format = match.group("format")
    assert "$request_method" in access_format
    assert "$uri" in access_format
    assert "$request_uri" not in access_format
    assert "$args" not in access_format
    assert "$http_referer" not in access_format
    assert "$request " not in access_format
    assert "access_log /dev/stdout path_only;" in nginx
    assert "access_log /dev/stdout combined;" not in nginx
    assert "location = /auth/google/callback" in nginx
    assert "error_log /dev/stderr crit;" in nginx


def test_production_nginx_rate_limits_every_public_auth_entrypoint() -> None:
    nginx = Path("deploy/nginx.production.conf").read_text(encoding="utf-8")
    callback = re.search(
        r"location = /auth/google/callback \{(?P<body>.*?)\n        \}",
        nginx,
        re.DOTALL,
    )

    assert "limit_req_zone $binary_remote_addr zone=auth_per_ip:10m rate=20r/m;" in nginx
    assert (
        "location ~ ^/(auth/(login|register|google/start|email/resend|password/forgot)"
        "|account/security/(password|email|google/(connect|disconnect))|admin/login)$" in nginx
    )
    assert "location ~ ^/auth/(email/verify|password/reset)$" in nginx
    assert "limit_req zone=auth_per_ip burst=10 nodelay;" in nginx
    assert callback is not None
    assert "limit_req zone=auth_per_ip burst=10 nodelay;" in callback.group("body")
    assert "limit_req_status 429;" in nginx


def test_google_oidc_environment_contract_contains_no_committed_credentials() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")
    environment = dict(
        line.split("=", 1)
        for line in example.splitlines()
        if line and not line.startswith("#") and "=" in line
    )

    assert environment["GOOGLE_OIDC_ENABLED"] == "false"
    for name in (
        "GOOGLE_OIDC_CLIENT_ID",
        "GOOGLE_OIDC_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "GOOGLE_OIDC_CLIENT_ID_FILE",
        "GOOGLE_OIDC_CLIENT_SECRET_FILE",
        "ALPHA_GOOGLE_OIDC_CLIENT_ID",
        "ALPHA_GOOGLE_OIDC_CLIENT_SECRET",
        "ALPHA_GOOGLE_REDIRECT_URI",
        "BETA_GOOGLE_OIDC_CLIENT_ID",
        "BETA_GOOGLE_OIDC_CLIENT_SECRET",
        "BETA_GOOGLE_REDIRECT_URI",
    ):
        assert environment[name] == ""
    assert environment["ALPHA_GOOGLE_OIDC_ENABLED"] == "false"
    assert environment["BETA_GOOGLE_OIDC_ENABLED"] == "false"

    production = Path("docker-compose.production.yml").read_text(encoding="utf-8")
    assert 'GOOGLE_OIDC_ENABLED: "${GOOGLE_OIDC_ENABLED:-false}"' in production

    oidc_override = Path("docker-compose.google-oidc.yml").read_text(encoding="utf-8")
    assert 'GOOGLE_OIDC_ENABLED: "true"' in oidc_override
    assert "GOOGLE_OIDC_CLIENT_ID_FILE: /run/secrets/google_oidc_client_id" in oidc_override
    assert "GOOGLE_OIDC_CLIENT_SECRET_FILE: /run/secrets/google_oidc_client_secret" in oidc_override
    assert "GOOGLE_OIDC_CLIENT_ID:" not in oidc_override
    assert "GOOGLE_OIDC_CLIENT_SECRET:" not in oidc_override


def test_account_email_environment_uses_disabled_base_and_secret_file_override() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")
    environment = dict(
        line.split("=", 1)
        for line in example.splitlines()
        if line and not line.startswith("#") and "=" in line
    )

    assert environment["ACCOUNT_EMAIL_ENABLED"] == "false"
    assert environment["SMTP_USE_STARTTLS"] == "true"
    assert environment["SMTP_PORT"] == "587"
    assert environment["SMTP_TIMEOUT_SECONDS"] == "10"
    for name in (
        "SMTP_HOST",
        "SMTP_USERNAME",
        "SMTP_PASSWORD",
        "SMTP_USERNAME_FILE",
        "SMTP_PASSWORD_FILE",
        "EMAIL_FROM_ADDRESS",
    ):
        assert environment[name] == ""

    production = Path("docker-compose.production.yml").read_text(encoding="utf-8")
    assert 'ACCOUNT_EMAIL_ENABLED: "${ACCOUNT_EMAIL_ENABLED:-false}"' in production
    assert "SMTP_USERNAME:" not in production
    assert "SMTP_PASSWORD:" not in production

    override = Path("docker-compose.smtp.yml").read_text(encoding="utf-8")
    assert 'ACCOUNT_EMAIL_ENABLED: "true"' in override
    assert "SMTP_USERNAME_FILE: /run/secrets/smtp_username" in override
    assert "SMTP_PASSWORD_FILE: /run/secrets/smtp_password" in override
    assert "${PRODUCTION_SECRETS_DIR" in override
    assert "SMTP_USERNAME:" not in override
    assert "SMTP_PASSWORD:" not in override


def test_combined_account_auth_operations_are_gated_and_keep_both_overrides() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    preflight = makefile.split("production-origin-account-auth-preflight:", 1)[1].split(
        "\nproduction-origin-account-auth-up:", 1
    )[0]
    up = makefile.split(
        "production-origin-account-auth-up: production-origin-account-auth-preflight", 1
    )[1].split("\nproduction-origin-account-auth-check:", 1)[0]
    check = makefile.split("production-origin-account-auth-check:", 1)[1].split(
        "\nproduction-origin-account-auth-status:", 1
    )[0]
    disable = makefile.split("production-origin-account-auth-disable:", 1)[1].split(
        "\n# Image-only rollback", 1
    )[0]
    override_flags = "-f docker-compose.smtp.yml -f docker-compose.google-oidc.yml"

    assert 'test "$(ACCOUNT_AUTH_CHANGE_APPROVED)" = "APPROVED"' in preflight
    assert 'test "$(ACCOUNT_AUTH_HOST_GATE_CONFIRMED)" = "PASSED"' in preflight
    assert 'test "$(ACCOUNT_AUTH_BACKUP_RESTORE_CONFIRMED)" = "VERIFIED"' in preflight
    assert preflight.count(override_flags) == 3
    assert preflight.index("config --quiet") < preflight.index("build web-production")
    assert preflight.index("build web-production") < preflight.index(
        "run --rm --no-deps web-production python -c"
    )
    assert 'app.config["ACCOUNT_EMAIL_ENABLED"] is True' in preflight
    assert 'app.config["GOOGLE_OIDC_ENABLED"] is True' in preflight
    assert override_flags in up
    assert "up -d --no-build --wait web-production" in up
    assert override_flags in check
    assert "scripts.check_production_https" in check
    assert "scripts.check_google_oidc_https" in check
    assert 'app.config["ACCOUNT_EMAIL_ENABLED"] is True' in check
    assert 'app.config["GOOGLE_OIDC_ENABLED"] is True' in check
    assert "flask --app wsgi db current" in check
    assert disable.count("ACCOUNT_EMAIL_ENABLED=false GOOGLE_OIDC_ENABLED=false") == 2
    assert override_flags not in disable
    assert "--no-build --no-deps --force-recreate --wait web-production" in disable

    readme = Path("README.md").read_text(encoding="utf-8")
    assert "production-origin-account-auth-preflight" in readme
    assert "production-origin-account-auth-up" in readme
    assert "production-origin-account-auth-check" in readme
    assert "production-origin-account-auth-disable" in readme
    assert "외부 자격증명이 없는 기본 배포" in readme


def test_public_demo_account_is_optional_and_bootstrapped_before_server_start() -> None:
    example = Path(".env.example").read_text(encoding="utf-8")
    environment = dict(
        line.split("=", 1)
        for line in example.splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    for name in (
        "DEMO_LOGIN_NAME",
        "DEMO_PUBLIC_PASSWORD",
        "ALPHA_DEMO_LOGIN_NAME",
        "ALPHA_DEMO_PUBLIC_PASSWORD",
        "BETA_DEMO_LOGIN_NAME",
        "BETA_DEMO_PUBLIC_PASSWORD",
    ):
        assert environment[name] == ""

    for compose_file in (
        "docker-compose.alpha.yml",
        "docker-compose.beta.yml",
        "docker-compose.production.yml",
    ):
        compose = Path(compose_file).read_text(encoding="utf-8")
        runtime = (
            Path("scripts/run_production_web.sh").read_text(encoding="utf-8")
            if compose_file == "docker-compose.production.yml"
            else compose
        )
        assert "auth bootstrap-demo" in runtime
        assert runtime.index("auth bootstrap-admin") < runtime.index("auth bootstrap-demo")
        assert runtime.index("auth bootstrap-demo") < runtime.index("gunicorn")
        assert "DEMO_LOGIN_NAME:" in compose
        assert "DEMO_PUBLIC_PASSWORD:" in compose

    production_runtime = Path("scripts/run_production_web.sh").read_text(encoding="utf-8")
    assert "0) ;;" in production_runtime
    makefile = Path("Makefile").read_text(encoding="utf-8")
    rollback = makefile.split("production-origin-rollback-app:", 1)[1].split(
        "production-origin-backup:", 1
    )[0]
    rollback_gate = "deploy/postgres_demo_rollback_gate.sql"
    assert f"METRICS_SQL={rollback_gate}" in rollback
    gate_sql = Path(rollback_gate).read_text(encoding="utf-8")
    assert "to_regclass('public.user_accounts')" in gate_sql
    assert "actor_ref = $1 AND status = $2" in gate_sql
    assert "OR actor_ref LIKE $3" in gate_sql
    assert "USING 'demo:public', 'ACTIVE', 'demo:role:%'" in gate_sql
    assert rollback.index(rollback_gate) < rollback.index("PRODUCTION_BOOTSTRAP_ADMIN_ON_STARTUP")

    readme = Path("README.md").read_text(encoding="utf-8")
    assert "공개 상담은 로그인 없이 끝까지 이용" in readme
    assert "직업위탁 재학생을 기본값" in readme
    assert "3학년 2학기는 선택 입력" in readme
    assert "공개 계산의 필수 입구가 아닙니다" in readme
