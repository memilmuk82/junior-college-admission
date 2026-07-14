from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
from pathlib import Path
from urllib.parse import quote

from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

HOST_PATTERN = re.compile(
    r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z"
)
FILE_MODE = 0o600
DIRECTORY_MODE = 0o700


def _exclusive_write(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def bootstrap_production(
    *,
    public_host: str,
    env_file: Path,
    secrets_dir: Path,
    admin_username: str,
) -> None:
    normalized_host = public_host.strip().lower()
    if not HOST_PATTERN.fullmatch(normalized_host):
        raise ValueError("공개 호스트 이름 형식이 유효하지 않습니다.")
    if not admin_username or any(character.isspace() for character in admin_username):
        raise ValueError("관리자 사용자 이름 형식이 유효하지 않습니다.")
    if env_file.exists() or secrets_dir.exists():
        raise FileExistsError("기존 production 환경 또는 secret 디렉터리를 덮어쓰지 않습니다.")

    secrets_dir.mkdir(parents=True, mode=DIRECTORY_MODE)
    secrets_dir.chmod(DIRECTORY_MODE)
    try:
        database_password = secrets.token_urlsafe(36)
        initial_admin_password = secrets.token_urlsafe(24)
        secret_values = {
            "app_secret_key": secrets.token_urlsafe(48),
            "postgres_password": database_password,
            "database_url": (
                "postgresql+psycopg://admission:"
                f"{quote(database_password, safe='')}@db-production:5432/admission"
            ),
            "admin_username": admin_username,
            "admin_password_hash": generate_password_hash(initial_admin_password),
            "byok_master_key": Fernet.generate_key().decode("ascii"),
            "initial_admin_password": initial_admin_password,
        }
        for name, value in secret_values.items():
            _exclusive_write(secrets_dir / name, value)

        absolute_secrets_dir = secrets_dir.resolve()
        env_lines = [
            "APP_ENV=production",
            f"PRODUCTION_SECRETS_DIR={absolute_secrets_dir}",
            f"SECRET_KEY_FILE={absolute_secrets_dir / 'app_secret_key'}",
            f"DATABASE_URL_FILE={absolute_secrets_dir / 'database_url'}",
            f"ADMIN_USERNAME_FILE={absolute_secrets_dir / 'admin_username'}",
            f"ADMIN_PASSWORD_HASH_FILE={absolute_secrets_dir / 'admin_password_hash'}",
            f"BYOK_MASTER_KEY_FILE={absolute_secrets_dir / 'byok_master_key'}",
            f"PUBLIC_BASE_URL=https://{normalized_host}",
            f"TRUSTED_HOSTS={normalized_host}",
            "TRUST_PROXY_HOPS=1",
            f"PRODUCTION_PUBLIC_BASE_URL=https://{normalized_host}",
            f"PRODUCTION_TRUSTED_HOSTS={normalized_host}",
            f"PRODUCTION_HEALTHCHECK_HOST={normalized_host}",
            "PRODUCTION_ORIGIN_PORT=8000",
            "PRODUCTION_PROXY_UID=101",
            "PRODUCTION_PROXY_GID=101",
            "PRODUCTION_POSTGRES_DB=admission",
            "PRODUCTION_POSTGRES_USER=admission",
            "PRODUCTION_WEB_WORKERS=2",
            "PRODUCTION_WEB_THREADS=2",
        ]
        env_file.parent.mkdir(parents=True, exist_ok=True)
        _exclusive_write(env_file, "\n".join(env_lines))
    except BaseException:
        shutil.rmtree(secrets_dir, ignore_errors=True)
        env_file.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="비밀값을 출력하지 않고 production 초기 secret을 생성합니다."
    )
    parser.add_argument("--public-host", required=True)
    parser.add_argument("--env-file", type=Path, default=Path(".env.production"))
    parser.add_argument("--secrets-dir", type=Path, default=Path("secrets/production"))
    parser.add_argument("--admin-username", default="admin")
    arguments = parser.parse_args()

    try:
        bootstrap_production(
            public_host=arguments.public_host,
            env_file=arguments.env_file,
            secrets_dir=arguments.secrets_dir,
            admin_username=arguments.admin_username,
        )
    except (FileExistsError, OSError, ValueError) as error:
        print(f"production secret 부트스트랩 실패: {error}")
        return 1
    print(
        "production secret 부트스트랩 통과: 비밀값을 출력하지 않고 "
        "환경 파일과 전용 secret 디렉터리를 생성했습니다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
