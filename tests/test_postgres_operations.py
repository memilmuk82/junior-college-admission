from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from pathlib import Path

from scripts.migration_head import current_migration_head


def _fake_docker(tmp_path: Path) -> tuple[Path, Path, Path]:
    executable = tmp_path / "docker"
    arguments = tmp_path / "arguments"
    standard_input = tmp_path / "standard-input"
    executable.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$@" >> "$CAPTURE_ARGUMENTS"\n'
        'if [ -n "${CAPTURE_STDIN:-}" ]; then cat > "$CAPTURE_STDIN"; fi\n'
        'if [ "${DOCKER_EXIT_CODE:-0}" != "0" ]; then exit "$DOCKER_EXIT_CODE"; fi\n'
        'case "$*" in\n'
        '  *pg_dump*) if [ "${EMIT_ARCHIVE:-0}" = "1" ]; then printf "synthetic-archive"; fi ;;\n'
        '  *pg_restore*--list*) printf "1; 0 0 TABLE DATA public synthetic postgres\\n" ;;\n'
        '  *version_num*) printf "%s" "${FAKE_MIGRATION_HEAD}" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)
    return executable, arguments, standard_input


def _operation_environment(
    executable: Path, arguments: Path, standard_input: Path
) -> dict[str, str]:
    return {
        **os.environ,
        "DOCKER_BIN": str(executable),
        "CAPTURE_ARGUMENTS": str(arguments),
        "CAPTURE_STDIN": str(standard_input),
        "COMPOSE_FILE": "docker-compose.production.yml",
        "COMPOSE_OVERRIDE_FILE": "docker-compose.host-nginx.yml",
        "COMPOSE_ENV_FILE": ".env.production",
        "DB_SERVICE": "db-production",
        "FAKE_MIGRATION_HEAD": current_migration_head(),
    }


def _write_backup_contract(backup: Path) -> None:
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    Path(f"{backup}.sha256").write_text(
        f"{digest}  {backup.name}\n",
        encoding="utf-8",
    )
    Path(f"{backup}.manifest").write_text(
        "manifest_version=1\n"
        f"archive_basename={backup.name}\n"
        f"archive_sha256={digest}\n"
        f"source_migration_head={current_migration_head()}\n"
        "table_data_entries=1\n",
        encoding="utf-8",
    )


def test_backup_is_private_atomic_and_targets_configured_service(tmp_path: Path) -> None:
    executable, arguments, standard_input = _fake_docker(tmp_path)
    environment = _operation_environment(executable, arguments, standard_input)
    environment["EMIT_ARCHIVE"] = "1"
    backup_dir = tmp_path / "backups"
    environment["BACKUP_DIR"] = str(backup_dir)

    subprocess.run(
        ["sh", "scripts/backup_postgres.sh"],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )

    backups = list(backup_dir.glob("*.dump"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b"synthetic-archive"
    assert stat.S_IMODE(backups[0].stat().st_mode) == 0o600
    assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700
    checksum = Path(f"{backups[0]}.sha256")
    assert checksum.is_file()
    manifest = Path(f"{backups[0]}.manifest")
    assert manifest.is_file()
    assert stat.S_IMODE(checksum.stat().st_mode) == 0o600
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600
    assert not list(backup_dir.glob(".admission_*"))
    captured = arguments.read_text(encoding="utf-8")
    assert "docker-compose.production.yml" in captured
    assert "docker-compose.host-nginx.yml" in captured
    assert ".env.production" in captured
    assert "db-production" in captured
    assert "--no-password" in captured
    assert "--lock-wait-timeout=10s" in captured


def test_failed_backup_removes_partial_files(tmp_path: Path) -> None:
    executable, arguments, standard_input = _fake_docker(tmp_path)
    environment = _operation_environment(executable, arguments, standard_input)
    environment["DOCKER_EXIT_CODE"] = "9"
    backup_dir = tmp_path / "backups"
    environment["BACKUP_DIR"] = str(backup_dir)

    result = subprocess.run(
        ["sh", "scripts/backup_postgres.sh"],
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 9
    assert not list(backup_dir.iterdir())


def test_backup_collision_preserves_existing_archive_and_checksum(tmp_path: Path) -> None:
    executable, arguments, standard_input = _fake_docker(tmp_path)
    environment = _operation_environment(executable, arguments, standard_input)
    environment["EMIT_ARCHIVE"] = "1"
    environment["BACKUP_STEM"] = "existing"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup = backup_dir / "existing.dump"
    checksum = backup_dir / "existing.dump.sha256"
    backup.write_bytes(b"preserve-archive")
    checksum.write_text("preserve-checksum\n", encoding="utf-8")
    environment["BACKUP_DIR"] = str(backup_dir)

    result = subprocess.run(
        ["sh", "scripts/backup_postgres.sh"],
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert backup.read_bytes() == b"preserve-archive"
    assert checksum.read_text(encoding="utf-8") == "preserve-checksum\n"


def test_backup_verification_reads_archive_without_database_restore(tmp_path: Path) -> None:
    executable, arguments, standard_input = _fake_docker(tmp_path)
    environment = _operation_environment(executable, arguments, standard_input)
    backup = tmp_path / "synthetic.dump"
    backup.write_bytes(b"synthetic-archive")
    _write_backup_contract(backup)
    environment["BACKUP_FILE"] = str(backup)

    subprocess.run(
        ["sh", "scripts/verify_postgres_backup.sh"],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert standard_input.read_bytes() == b"synthetic-archive"
    captured = arguments.read_text(encoding="utf-8")
    assert "pg_restore" in captured
    assert "--list" in captured
    assert "--clean" not in captured
    assert "--create" not in captured


def test_backup_verification_requires_checksum_sidecar(tmp_path: Path) -> None:
    executable, arguments, standard_input = _fake_docker(tmp_path)
    environment = _operation_environment(executable, arguments, standard_input)
    backup = tmp_path / "synthetic.dump"
    backup.write_bytes(b"synthetic-archive")
    environment["BACKUP_FILE"] = str(backup)

    result = subprocess.run(
        ["sh", "scripts/verify_postgres_backup.sh"],
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0


def test_backup_verification_rejects_sidecar_for_a_different_archive(tmp_path: Path) -> None:
    executable, arguments, standard_input = _fake_docker(tmp_path)
    environment = _operation_environment(executable, arguments, standard_input)
    backup = tmp_path / "synthetic.dump"
    backup.write_bytes(b"synthetic-archive")
    _write_backup_contract(backup)
    other = tmp_path / "other.dump"
    other.write_bytes(b"other-archive")
    other_digest = hashlib.sha256(other.read_bytes()).hexdigest()
    Path(f"{backup}.sha256").write_text(
        f"{other_digest}  {other.name}\n",
        encoding="utf-8",
    )
    environment["BACKUP_FILE"] = str(backup)

    result = subprocess.run(
        ["sh", "scripts/verify_postgres_backup.sh"],
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0


def test_backup_verification_requires_source_manifest(tmp_path: Path) -> None:
    executable, arguments, standard_input = _fake_docker(tmp_path)
    environment = _operation_environment(executable, arguments, standard_input)
    backup = tmp_path / "synthetic.dump"
    backup.write_bytes(b"synthetic-archive")
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    Path(f"{backup}.sha256").write_text(
        f"{digest}  {backup.name}\n",
        encoding="utf-8",
    )
    environment["BACKUP_FILE"] = str(backup)

    result = subprocess.run(
        ["sh", "scripts/verify_postgres_backup.sh"],
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0


def test_isolated_restore_contract_has_no_live_network_volume_or_port() -> None:
    script = Path("scripts/verify_postgres_restore.sh").read_text(encoding="utf-8")

    assert "--network none" in script
    assert "--tmpfs" in script
    assert "/var/lib/postgresql/data" in script
    assert "RESTORE_TMPFS_SIZE_MB" in script
    assert "--exit-on-error" in script
    assert "--no-owner" in script
    assert "--no-privileges" in script
    assert "postmaster.pid" in script
    assert "--pull never" in script
    assert "--pids-limit" in script
    assert "--memory" in script
    assert "--cpus" in script
    assert "no-new-privileges:true" in script
    assert 'rm -f "$container_id"' in script
    assert 'rm -f "$container_name"' not in script
    assert "scripts.migration_head" in script
    assert "source_migration_head" in script
    assert "table_data_entries" in script
    assert "EXPECTED_SYNTHETIC_SENTINEL_ID" in script
    assert "EXPECTED_SYNTHETIC_SENTINEL_NAME" in script
    assert '"$timeout_bin" 30 "$docker_bin" rm -f' in script
    assert "docker-compose.production" not in script
    assert "production_postgres_data" not in script
    assert "/run/secrets" not in script
    assert not re.search(r"(?:^|\s)(?:-p|--publish)(?:\s|=)", script)


def test_repository_has_one_migration_head() -> None:
    assert re.fullmatch(r"[0-9a-f]+", current_migration_head())


def test_backup_restore_harness_does_not_reuse_glob_as_compose_command() -> None:
    script = Path("scripts/check_postgres_backup_restore.sh").read_text(encoding="utf-8")
    before_glob, after_glob = script.split('set -- "$backup_dir"/*.dump', maxsplit=1)

    assert '"$@" images' in before_glob
    assert '"$@"' not in after_glob
    assert "EXPECTED_SYNTHETIC_SENTINEL_NAME" in after_glob


def test_metrics_contract_is_read_only_and_omits_query_text(tmp_path: Path) -> None:
    executable, arguments, standard_input = _fake_docker(tmp_path)
    environment = _operation_environment(executable, arguments, standard_input)

    subprocess.run(
        ["sh", "scripts/collect_postgres_metrics.sh"],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )

    sql = standard_input.read_text(encoding="utf-8")
    assert "BEGIN TRANSACTION READ ONLY" in sql
    assert "pg_stat_database" in sql
    assert "pg_stat_activity" in sql
    assert "pg_stat_io" in sql
    assert "pg_stat_wal" in sql
    assert "pg_stat_checkpointer" in sql
    assert "clock_timestamp()" in sql
    assert "stats_reset" in sql
    assert "pg_stat_statements" in sql
    assert "statement_totals" in sql
    assert "statement_top" in sql
    assert "total_exec_time" in sql
    assert "mean_exec_time" in sql
    assert "shared_blks_read" in sql
    assert "temp_blks_read" in sql
    assert not re.search(
        r"\b(?:INSERT|UPDATE|DELETE|TRUNCATE|DROP|ALTER|CREATE|GRANT|REVOKE|RESET)\b",
        sql,
        re.IGNORECASE,
    )
    assert not re.search(r"SELECT\s+query\b", sql, re.IGNORECASE)
    captured_arguments = arguments.read_text(encoding="utf-8")
    assert "db-production" in captured_arguments
    assert "-X" in captured_arguments


def test_production_metrics_can_require_a_dedicated_user(tmp_path: Path) -> None:
    executable, arguments, standard_input = _fake_docker(tmp_path)
    environment = _operation_environment(executable, arguments, standard_input)
    environment["REQUIRE_METRICS_DB_USER"] = "1"

    result = subprocess.run(
        ["sh", "scripts/collect_postgres_metrics.sh"],
        check=False,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "METRICS_DB_USER" in result.stderr
    assert not arguments.exists()
