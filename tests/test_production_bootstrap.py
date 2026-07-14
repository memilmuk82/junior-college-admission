from __future__ import annotations

import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from werkzeug.security import check_password_hash

from scripts.bootstrap_production import bootstrap_production


def test_bootstrap_creates_isolated_bounded_production_secrets(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.production"
    secrets_dir = tmp_path / "production-secrets"

    bootstrap_production(
        public_host="service.example.test",
        env_file=env_file,
        secrets_dir=secrets_dir,
        admin_username="synthetic-admin",
    )

    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(secrets_dir.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in secrets_dir.iterdir())
    initial_password = (secrets_dir / "initial_admin_password").read_text().strip()
    password_hash = (secrets_dir / "admin_password_hash").read_text().strip()
    assert check_password_hash(password_hash, initial_password)
    Fernet((secrets_dir / "byok_master_key").read_bytes().strip())

    env_text = env_file.read_text(encoding="utf-8")
    assert "PUBLIC_BASE_URL=https://service.example.test" in env_text
    assert "TRUSTED_HOSTS=service.example.test" in env_text
    assert "TRUST_PROXY_HOPS=1" in env_text
    assert "https://service.example.test" in env_text
    assert "PRODUCTION_ORIGIN_PORT=8000" in env_text
    assert initial_password not in env_text
    assert (secrets_dir / "app_secret_key").read_text().strip() not in env_text
    assert (secrets_dir / "postgres_password").read_text().strip() not in env_text


def test_bootstrap_refuses_existing_environment_without_overwrite(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.production"
    secrets_dir = tmp_path / "production-secrets"
    env_file.write_text("preserve=true\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        bootstrap_production(
            public_host="service.example.test",
            env_file=env_file,
            secrets_dir=secrets_dir,
            admin_username="synthetic-admin",
        )

    assert env_file.read_text(encoding="utf-8") == "preserve=true\n"
    assert not secrets_dir.exists()


@pytest.mark.parametrize(
    "public_host", ["", "https://service.example.test", "service.example.test/path"]
)
def test_bootstrap_rejects_invalid_public_host(tmp_path: Path, public_host: str) -> None:
    with pytest.raises(ValueError):
        bootstrap_production(
            public_host=public_host,
            env_file=tmp_path / ".env.production",
            secrets_dir=tmp_path / "production-secrets",
            admin_username="synthetic-admin",
        )
