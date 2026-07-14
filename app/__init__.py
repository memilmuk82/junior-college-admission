import os
import re
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

DEVELOPMENT_SECRET_KEY = "development-only-change-me"
SCRYPT_PASSWORD_HASH = re.compile(r"scrypt:\d+:\d+:\d+\$[^$]{8,}\$[0-9a-f]{64,}\Z")
MAX_SECRET_FILE_BYTES = 64 * 1024


def _environment_value(name: str, default: str | None = None) -> str | None:
    direct_value = os.environ.get(name)
    file_name = os.environ.get(f"{name}_FILE")
    if direct_value is not None and file_name:
        raise RuntimeError(f"운영 비밀값 입력이 중복되었습니다: {name}, {name}_FILE")
    if not file_name:
        return direct_value if direct_value is not None else default

    path = Path(file_name)
    try:
        if not path.is_file() or path.stat().st_size > MAX_SECRET_FILE_BYTES:
            raise RuntimeError(f"운영 비밀값 파일이 유효하지 않습니다: {name}_FILE")
        value = path.read_text(encoding="utf-8").rstrip("\r\n")
    except (OSError, UnicodeError) as error:
        raise RuntimeError(f"운영 비밀값 파일을 읽을 수 없습니다: {name}_FILE") from error
    if not value or "\n" in value or "\r" in value:
        raise RuntimeError(f"운영 비밀값 파일 형식이 유효하지 않습니다: {name}_FILE")
    return value


def _environment_hosts(value: str | None) -> list[str]:
    if not value:
        return []
    return [host.strip() for host in value.split(",") if host.strip()]


def _valid_fernet_key(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        Fernet(value.encode("ascii"))
    except (TypeError, ValueError):
        return False
    return True


def _configure_production_security(app: Flask) -> None:
    if app.config.get("APP_ENV") != "production":
        return

    trusted_hosts = app.config.get("TRUSTED_HOSTS")
    if isinstance(trusted_hosts, str):
        trusted_hosts = _environment_hosts(trusted_hosts)

    failures: list[str] = []
    secret_key = app.config.get("SECRET_KEY")
    if (
        not isinstance(secret_key, str)
        or len(secret_key) < 32
        or secret_key == DEVELOPMENT_SECRET_KEY
    ):
        failures.append("SECRET_KEY")
    database_url = app.config.get("DATABASE_URL")
    if not isinstance(database_url, str) or not database_url.startswith(
        ("postgresql+psycopg://", "postgresql://")
    ):
        failures.append("DATABASE_URL")
    if not isinstance(app.config.get("ADMIN_USERNAME"), str) or not app.config["ADMIN_USERNAME"]:
        failures.append("ADMIN_USERNAME")
    password_hash = app.config.get("ADMIN_PASSWORD_HASH")
    if not isinstance(password_hash, str) or not SCRYPT_PASSWORD_HASH.fullmatch(password_hash):
        failures.append("ADMIN_PASSWORD_HASH")
    if not _valid_fernet_key(app.config.get("BYOK_MASTER_KEY")):
        failures.append("BYOK_MASTER_KEY")
    if not isinstance(trusted_hosts, list) or not trusted_hosts:
        failures.append("TRUSTED_HOSTS")
    public_base_url = app.config.get("PUBLIC_BASE_URL")
    parsed_base_url = urlparse(public_base_url) if isinstance(public_base_url, str) else None
    if (
        parsed_base_url is None
        or parsed_base_url.scheme != "https"
        or not parsed_base_url.hostname
        or parsed_base_url.hostname not in (trusted_hosts or [])
        or parsed_base_url.path not in {"", "/"}
        or parsed_base_url.params
        or parsed_base_url.query
        or parsed_base_url.fragment
    ):
        failures.append("PUBLIC_BASE_URL")
    try:
        proxy_hops = int(app.config.get("TRUST_PROXY_HOPS", 0))
    except (TypeError, ValueError):
        proxy_hops = 0
    if proxy_hops != 1:
        failures.append("TRUST_PROXY_HOPS")
    if failures:
        raise RuntimeError(
            "운영 시작 조건이 충족되지 않았습니다: " + ", ".join(sorted(set(failures)))
        )

    app.config.update(
        TRUSTED_HOSTS=trusted_hosts,
        TRUST_PROXY_HOPS=proxy_hops,
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PREFERRED_URL_SCHEME="https",
    )
    app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
        app.wsgi_app,
        x_for=proxy_hops,
        x_proto=proxy_hops,
        x_host=proxy_hops,
        x_port=proxy_hops,
    )


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        APP_ENV=os.environ.get("APP_ENV", "development"),
        SECRET_KEY=_environment_value("SECRET_KEY", DEVELOPMENT_SECRET_KEY),
        DATABASE_URL=_environment_value("DATABASE_URL"),
        TEMP_UPLOAD_ROOT=os.environ.get(
            "TEMP_UPLOAD_ROOT", "/tmp/junior-college-admission/uploads"
        ),
        ADMIN_USERNAME=_environment_value("ADMIN_USERNAME"),
        ADMIN_PASSWORD_HASH=_environment_value("ADMIN_PASSWORD_HASH"),
        BYOK_MASTER_KEY=_environment_value("BYOK_MASTER_KEY"),
        PUBLIC_BASE_URL=os.environ.get("PUBLIC_BASE_URL"),
        TRUSTED_HOSTS=_environment_hosts(os.environ.get("TRUSTED_HOSTS")),
        TRUST_PROXY_HOPS=os.environ.get("TRUST_PROXY_HOPS", "0"),
    )

    if test_config:
        app.config.update(test_config)

    _configure_production_security(app)

    from app.database import init_database

    init_database(app)

    from app.routes import bp

    app.register_blueprint(bp)
    from app.admin_routes import bp as admin_bp

    app.register_blueprint(admin_bp)
    return app
