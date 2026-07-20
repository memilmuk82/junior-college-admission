import os
import re
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet
from flask import Flask
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.middleware.proxy_fix import ProxyFix

DEVELOPMENT_SECRET_KEY = "development-only-change-me"
SCRYPT_PASSWORD_HASH = re.compile(r"scrypt:\d+:\d+:\d+\$[^$]{8,}\$[0-9a-f]{64,}\Z")
BARE_EMAIL_ADDRESS = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")
APPLICATION_ROOT_PATTERN = re.compile(r"/(?:[A-Za-z0-9._~-]+(?:/[A-Za-z0-9._~-]+)*)?\Z")
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


def _environment_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"환경변수 형식이 유효하지 않습니다: {name}")


def _valid_fernet_key(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        Fernet(value.encode("ascii"))
    except (TypeError, ValueError):
        return False
    return True


def _valid_smtp_host(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 253
        and value == value.strip()
        and not any(character.isspace() for character in value)
        and "://" not in value
    )


def _valid_bare_email_address(value: object) -> bool:
    return (
        isinstance(value, str)
        and 3 <= len(value) <= 320
        and value == value.strip()
        and BARE_EMAIL_ADDRESS.fullmatch(value) is not None
    )


def _valid_single_line_secret(value: object) -> bool:
    return isinstance(value, str) and bool(value) and "\n" not in value and "\r" not in value


def _valid_bounded_integer(value: object, *, minimum: int, maximum: int) -> bool:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return False
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return False
    return str(parsed) == str(value).strip() and minimum <= parsed <= maximum


def _valid_bounded_number(value: object, *, minimum: float, maximum: float) -> bool:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return False
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False
    return minimum <= parsed <= maximum


def _application_root(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not APPLICATION_ROOT_PATTERN.fullmatch(normalized):
        return None
    return normalized.rstrip("/") or "/"


def _configure_deployed_security(app: Flask) -> None:
    environment = app.config.get("APP_ENV")
    if environment not in {"production", "demo-sandbox"}:
        return

    demo_sandbox = environment == "demo-sandbox"

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
    if not demo_sandbox:
        if (
            not isinstance(app.config.get("ADMIN_USERNAME"), str)
            or not app.config["ADMIN_USERNAME"]
        ):
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
    application_root = _application_root(app.config.get("APPLICATION_ROOT"))
    expected_base_path = "" if application_root == "/" else application_root
    if (
        parsed_base_url is None
        or parsed_base_url.scheme != "https"
        or not parsed_base_url.hostname
        or parsed_base_url.hostname not in (trusted_hosts or [])
        or parsed_base_url.path.rstrip("/") != expected_base_path
        or parsed_base_url.params
        or parsed_base_url.query
        or parsed_base_url.fragment
    ):
        failures.append("PUBLIC_BASE_URL")
    if application_root is None:
        failures.append("APPLICATION_ROOT")
    try:
        proxy_hops = int(app.config.get("TRUST_PROXY_HOPS", 0))
    except (TypeError, ValueError):
        proxy_hops = 0
    if proxy_hops != 1:
        failures.append("TRUST_PROXY_HOPS")
    if demo_sandbox:
        if app.config.get("DEMO_SANDBOX_ENABLED") is not True:
            failures.append("DEMO_SANDBOX_ENABLED")
        instance_id = app.config.get("DEMO_SANDBOX_INSTANCE_ID")
        if not isinstance(instance_id, str) or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]{2,47}", instance_id
        ):
            failures.append("DEMO_SANDBOX_INSTANCE_ID")
        if app.config.get("GOOGLE_OIDC_ENABLED"):
            failures.append("GOOGLE_OIDC_ENABLED")
        if app.config.get("DEMO_GOOGLE_STUB_ENABLED") is not True:
            failures.append("DEMO_GOOGLE_STUB_ENABLED")
        if app.config.get("DEMO_EMAIL_OUTBOX_ENABLED") is not True:
            failures.append("DEMO_EMAIL_OUTBOX_ENABLED")
        if app.config.get("DEMO_CRAWLER_FIXTURE_ENABLED") is not True:
            failures.append("DEMO_CRAWLER_FIXTURE_ENABLED")
        if app.config.get("SESSION_COOKIE_NAME") in {None, "", "session"}:
            failures.append("SESSION_COOKIE_NAME")
        if app.config.get("SESSION_COOKIE_PATH") != application_root:
            failures.append("SESSION_COOKIE_PATH")
    elif any(
        app.config.get(name)
        for name in (
            "DEMO_SANDBOX_ENABLED",
            "DEMO_GOOGLE_STUB_ENABLED",
            "DEMO_EMAIL_OUTBOX_ENABLED",
            "DEMO_CRAWLER_FIXTURE_ENABLED",
        )
    ):
        failures.append("DEMO_SANDBOX_ENABLED")

    if app.config.get("GOOGLE_OIDC_ENABLED"):
        if not isinstance(app.config.get("GOOGLE_OIDC_CLIENT_ID"), str) or not app.config.get(
            "GOOGLE_OIDC_CLIENT_ID"
        ):
            failures.append("GOOGLE_OIDC_CLIENT_ID")
        if not isinstance(app.config.get("GOOGLE_OIDC_CLIENT_SECRET"), str) or not app.config.get(
            "GOOGLE_OIDC_CLIENT_SECRET"
        ):
            failures.append("GOOGLE_OIDC_CLIENT_SECRET")
        redirect_uri = app.config.get("GOOGLE_REDIRECT_URI")
        if redirect_uri:
            parsed_redirect = urlparse(redirect_uri) if isinstance(redirect_uri, str) else None
            if (
                parsed_redirect is None
                or parsed_redirect.scheme != "https"
                or parsed_redirect.hostname not in (trusted_hosts or [])
                or parsed_redirect.path != "/auth/google/callback"
                or parsed_redirect.params
                or parsed_redirect.query
                or parsed_redirect.fragment
            ):
                failures.append("GOOGLE_REDIRECT_URI")
    if app.config.get("ACCOUNT_EMAIL_ENABLED") and not demo_sandbox:
        if not _valid_smtp_host(app.config.get("SMTP_HOST")):
            failures.append("SMTP_HOST")
        if not _valid_bounded_integer(app.config.get("SMTP_PORT"), minimum=1, maximum=65535):
            failures.append("SMTP_PORT")
        if not _valid_single_line_secret(app.config.get("SMTP_USERNAME")):
            failures.append("SMTP_USERNAME")
        if not _valid_single_line_secret(app.config.get("SMTP_PASSWORD")):
            failures.append("SMTP_PASSWORD")
        if app.config.get("SMTP_USE_STARTTLS") is not True:
            failures.append("SMTP_USE_STARTTLS")
        if not _valid_bare_email_address(app.config.get("EMAIL_FROM_ADDRESS")):
            failures.append("EMAIL_FROM_ADDRESS")
        if not _valid_bounded_number(
            app.config.get("SMTP_TIMEOUT_SECONDS"), minimum=0.1, maximum=30
        ):
            failures.append("SMTP_TIMEOUT_SECONDS")
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
        x_prefix=proxy_hops if demo_sandbox else 0,
    )

    @app.after_request
    def add_production_security_headers(response):  # type: ignore[no-untyped-def]
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Frame-Options", "DENY")
        return response


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        APP_ENV=os.environ.get("APP_ENV", "development"),
        APPLICATION_ROOT=os.environ.get("APPLICATION_ROOT", "/"),
        SESSION_COOKIE_NAME=os.environ.get("SESSION_COOKIE_NAME", "session"),
        SESSION_COOKIE_PATH=os.environ.get("SESSION_COOKIE_PATH", "/"),
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
        GOOGLE_OIDC_ENABLED=_environment_bool("GOOGLE_OIDC_ENABLED"),
        GOOGLE_OIDC_CLIENT_ID=_environment_value("GOOGLE_OIDC_CLIENT_ID"),
        GOOGLE_OIDC_CLIENT_SECRET=_environment_value("GOOGLE_OIDC_CLIENT_SECRET"),
        GOOGLE_REDIRECT_URI=os.environ.get("GOOGLE_REDIRECT_URI"),
        ACCOUNT_EMAIL_ENABLED=_environment_bool("ACCOUNT_EMAIL_ENABLED"),
        SMTP_HOST=os.environ.get("SMTP_HOST"),
        SMTP_PORT=os.environ.get("SMTP_PORT", "587"),
        SMTP_USERNAME=_environment_value("SMTP_USERNAME"),
        SMTP_PASSWORD=_environment_value("SMTP_PASSWORD"),
        SMTP_USE_STARTTLS=_environment_bool("SMTP_USE_STARTTLS", True),
        EMAIL_FROM_ADDRESS=os.environ.get("EMAIL_FROM_ADDRESS"),
        SMTP_TIMEOUT_SECONDS=os.environ.get("SMTP_TIMEOUT_SECONDS", "10"),
        ACCOUNT_EMAIL_OUTBOX=None,
        ACCOUNT_EMAIL_TRANSPORT=None,
        DEMO_LOGIN_NAME=os.environ.get("DEMO_LOGIN_NAME"),
        DEMO_PUBLIC_PASSWORD=_environment_value("DEMO_PUBLIC_PASSWORD"),
        DEMO_SANDBOX_PUBLIC_PASSWORD=_environment_value("DEMO_SANDBOX_PUBLIC_PASSWORD"),
        DEMO_SANDBOX_ENTRY_URL=os.environ.get("DEMO_SANDBOX_ENTRY_URL"),
        DEMO_SANDBOX_ENABLED=_environment_bool("DEMO_SANDBOX_ENABLED"),
        DEMO_SANDBOX_INSTANCE_ID=os.environ.get("DEMO_SANDBOX_INSTANCE_ID"),
        DEMO_EMAIL_OUTBOX_ENABLED=_environment_bool("DEMO_EMAIL_OUTBOX_ENABLED"),
        DEMO_GOOGLE_STUB_ENABLED=_environment_bool("DEMO_GOOGLE_STUB_ENABLED"),
        DEMO_CRAWLER_FIXTURE_ENABLED=_environment_bool("DEMO_CRAWLER_FIXTURE_ENABLED"),
        # 환경변수 관리자 로그인은 로컬 개발 호환용이다. alpha/beta/production은
        # 시작 시 DB 관리자를 부트스트랩하고 DB 인증만 사용한다.
        ALLOW_LEGACY_ADMIN_LOGIN=os.environ.get("APP_ENV", "development") == "development",
    )

    if test_config:
        app.config.update(test_config)

    if app.config.get("DEMO_EMAIL_OUTBOX_ENABLED"):
        if app.config.get("DEMO_SANDBOX_ENABLED") is not True:
            raise RuntimeError(
                "체험 메일함은 격리 체험 환경에서만 사용할 수 있습니다: DEMO_SANDBOX_ENABLED"
            )
        app.config.update(
            ACCOUNT_EMAIL_ENABLED=True,
            ACCOUNT_EMAIL_OUTBOX=(
                app.config.get("ACCOUNT_EMAIL_OUTBOX")
                if app.config.get("ACCOUNT_EMAIL_OUTBOX") is not None
                else []
            ),
        )

    _configure_deployed_security(app)

    from app.database import init_database

    init_database(app)

    @app.errorhandler(SQLAlchemyError)
    def handle_database_error(_error: SQLAlchemyError):  # type: ignore[no-untyped-def]
        # SQLAlchemy 예외 문자열에는 statement parameter가 포함될 수 있다.
        # 회원 이메일·표시명·password hash가 로그에 남지 않도록 예외 객체를
        # 기록하지 않고, 세션만 안전하게 정리한 뒤 일반화된 응답을 반환한다.
        from app.database import db

        try:
            db.session.rollback()
        except SQLAlchemyError:
            db.session.remove()
        app.logger.warning("데이터베이스 요청을 처리할 수 없습니다.")
        response = app.response_class(
            "요청을 처리할 수 없습니다. 잠시 후 다시 시도하세요.",
            status=503,
            mimetype="text/plain",
        )
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    from app.auth import register_auth_cli

    register_auth_cli(app)
    from app.services.demo_sandbox import register_demo_sandbox_cli

    register_demo_sandbox_cli(app)
    from app.phase14_cli import register_phase14_cli

    register_phase14_cli(app)
    from app.services.google_oidc import init_google_oidc

    init_google_oidc(app)

    from app.routes import bp

    app.register_blueprint(bp)
    from app.auth_routes import bp as auth_bp

    app.register_blueprint(auth_bp)
    from app.admin_routes import bp as admin_bp

    app.register_blueprint(admin_bp)
    from app.admission_result_import_routes import bp as admission_result_import_bp

    app.register_blueprint(admission_result_import_bp)
    from app.account_routes import bp as account_bp

    app.register_blueprint(account_bp)
    from app.teacher_routes import bp as teacher_bp

    app.register_blueprint(teacher_bp)
    from app.source_document_routes import bp as source_admin_bp

    app.register_blueprint(source_admin_bp)
    from app.member_routes import bp as member_bp

    app.register_blueprint(member_bp)
    return app
