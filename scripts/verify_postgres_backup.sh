#!/usr/bin/env sh
set -eu

backup_file=${BACKUP_FILE:?BACKUP_FILE must be set}
docker_bin=${DOCKER_BIN:-docker}
timeout_bin=${TIMEOUT_BIN:-timeout}
verify_timeout_seconds=${VERIFY_TIMEOUT_SECONDS:-600}
compose_file=${COMPOSE_FILE:-docker-compose.yml}
compose_override_file=${COMPOSE_OVERRIDE_FILE:-}
compose_env_file=${COMPOSE_ENV_FILE:-}
db_service=${DB_SERVICE:-db}

case "$verify_timeout_seconds" in
  ''|*[!0-9]*)
    printf 'VERIFY_TIMEOUT_SECONDS는 양의 정수여야 합니다.\n' >&2
    exit 1
    ;;
esac
test "$verify_timeout_seconds" -gt 0

test -f "$backup_file"
test -s "$backup_file"
test -f "$backup_file.sha256"
test -f "$backup_file.manifest"
backup_basename=$(basename "$backup_file")
actual_digest=$(sha256sum "$backup_file" | awk '{print $1}')
expected_checksum_line="$actual_digest  $backup_basename"
test "$(wc -l < "$backup_file.sha256" | tr -d ' ')" -eq 1
test "$(cat "$backup_file.sha256")" = "$expected_checksum_line"

test "$(grep -c '^manifest_version=' "$backup_file.manifest")" -eq 1
test "$(grep -c '^archive_basename=' "$backup_file.manifest")" -eq 1
test "$(grep -c '^archive_sha256=' "$backup_file.manifest")" -eq 1
test "$(grep -c '^source_migration_head=' "$backup_file.manifest")" -eq 1
test "$(grep -c '^table_data_entries=' "$backup_file.manifest")" -eq 1
test "$(wc -l < "$backup_file.manifest" | tr -d ' ')" -eq 5
test "$(sed -n 's/^manifest_version=//p' "$backup_file.manifest")" = "1"
test "$(sed -n 's/^archive_basename=//p' "$backup_file.manifest")" = "$backup_basename"
test "$(sed -n 's/^archive_sha256=//p' "$backup_file.manifest")" = "$actual_digest"
source_head=$(sed -n 's/^source_migration_head=//p' "$backup_file.manifest")
table_data_entries=$(sed -n 's/^table_data_entries=//p' "$backup_file.manifest")
case "$source_head" in
  ''|*[!0-9a-f]*)
    printf '백업 원본 Alembic head 형식이 유효하지 않습니다.\n' >&2
    exit 1
    ;;
esac
case "$table_data_entries" in
  ''|*[!0-9]*)
    printf '백업 TABLE DATA 항목 수 형식이 유효하지 않습니다.\n' >&2
    exit 1
    ;;
esac
test "$table_data_entries" -gt 0

set -- "$docker_bin" compose -f "$compose_file"
if [ -n "$compose_override_file" ]; then
  set -- "$@" -f "$compose_override_file"
fi
if [ -n "$compose_env_file" ]; then
  set -- "$@" --env-file "$compose_env_file"
fi

archive_listing=$("$timeout_bin" "$verify_timeout_seconds" "$@" exec -T "$db_service" \
  pg_restore --list < "$backup_file")
actual_table_data_entries=$(printf '%s\n' "$archive_listing" | \
  awk '/ TABLE DATA / { count += 1 } END { print count + 0 }')
test "$actual_table_data_entries" -eq "$table_data_entries"
(
  cd "$(dirname "$backup_file")"
  sha256sum "$(basename "$backup_file")"
)
printf 'PostgreSQL 백업 archive 검증 통과\n'
