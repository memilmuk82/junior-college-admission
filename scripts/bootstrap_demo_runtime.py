from __future__ import annotations

import argparse
import os
import secrets
import shutil
from pathlib import Path
from urllib.parse import quote

from cryptography.fernet import Fernet

FILE_MODE = 0o600
DIRECTORY_MODE = 0o700
EXPECTED_PUBLIC_BASE_URL = "https://admission.memilmuk82.com/demo"
EXPECTED_PUBLIC_HOST = "admission.memilmuk82.com"


def _exclusive_write(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, FILE_MODE)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.write("\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _validated_public_base_url(value: str) -> tuple[str, str]:
    normalized = value.strip().rstrip("/")
    if normalized != EXPECTED_PUBLIC_BASE_URL:
        raise ValueError(f"체험 공개 URL은 {EXPECTED_PUBLIC_BASE_URL} 이어야 합니다.")
    return normalized, EXPECTED_PUBLIC_HOST


def bootstrap_demo_runtime(
    *,
    public_base_url: str,
    env_file: Path,
    secrets_dir: Path,
) -> None:
    normalized_url, public_host = _validated_public_base_url(public_base_url)
    if env_file.exists() or secrets_dir.exists():
        raise FileExistsError("기존 demo 환경 또는 secret 디렉터리를 덮어쓰지 않습니다.")

    secrets_dir.mkdir(parents=True, mode=DIRECTORY_MODE)
    secrets_dir.chmod(DIRECTORY_MODE)
    try:
        database_password = secrets.token_urlsafe(36)
        secret_values = {
            "demo_app_secret_key": secrets.token_urlsafe(48),
            "demo_postgres_password": database_password,
            "demo_database_url": (
                "postgresql+psycopg://admission_demo:"
                f"{quote(database_password, safe='')}@db-demo:5432/admission_demo"
            ),
            "demo_byok_master_key": Fernet.generate_key().decode("ascii"),
            "demo_public_password": secrets.token_urlsafe(15),
        }
        for name, value in secret_values.items():
            _exclusive_write(secrets_dir / name, value)

        trusted_hosts = list(dict.fromkeys((public_host, "localhost", "127.0.0.1")))
        env_lines = [
            f"DEMO_SECRETS_DIR={secrets_dir.resolve()}",
            f"DEMO_PUBLIC_BASE_URL={normalized_url}",
            f"DEMO_TRUSTED_HOSTS={','.join(trusted_hosts)}",
            f"DEMO_HEALTHCHECK_HOST={public_host}",
            "DEMO_ORIGIN_PORT=8002",
            "DEMO_POSTGRES_DB=admission_demo",
            "DEMO_POSTGRES_USER=admission_demo",
            f"DEMO_APP_UID={os.getuid()}",
            f"DEMO_APP_GID={os.getgid()}",
            "DEMO_WEB_WORKERS=1",
            "DEMO_WEB_THREADS=4",
        ]
        env_file.parent.mkdir(parents=True, exist_ok=True)
        _exclusive_write(env_file, "\n".join(env_lines))
    except BaseException:
        shutil.rmtree(secrets_dir, ignore_errors=True)
        env_file.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="비밀값을 출력하지 않고 격리 체험 환경의 로컬 설정을 생성합니다."
    )
    parser.add_argument(
        "--public-base-url",
        default=EXPECTED_PUBLIC_BASE_URL,
        help="외부에서 체험 화면에 접근할 /demo 기준 URL",
    )
    parser.add_argument("--env-file", type=Path, default=Path(".env.demo"))
    parser.add_argument("--secrets-dir", type=Path, default=Path("secrets/demo"))
    arguments = parser.parse_args()

    try:
        bootstrap_demo_runtime(
            public_base_url=arguments.public_base_url,
            env_file=arguments.env_file,
            secrets_dir=arguments.secrets_dir,
        )
    except (FileExistsError, OSError, ValueError) as error:
        print(f"demo runtime secret 부트스트랩 실패: {error}")
        return 1
    print(
        "demo runtime secret 부트스트랩 통과: 비밀값을 출력하지 않고 "
        "전용 환경 파일과 secret 디렉터리를 생성했습니다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
