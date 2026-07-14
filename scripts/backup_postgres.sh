#!/usr/bin/env sh
set -eu
umask 077

backup_dir=${BACKUP_DIR:-backups}
timestamp=$(date +%Y%m%d_%H%M%S)
backup_stem=${BACKUP_STEM:-admission_${timestamp}_$$}
backup_file="$backup_dir/$backup_stem.dump"
checksum_file="$backup_file.sha256"
manifest_file="$backup_file.manifest"
docker_bin=${DOCKER_BIN:-docker}
timeout_bin=${TIMEOUT_BIN:-timeout}
backup_timeout_seconds=${BACKUP_TIMEOUT_SECONDS:-600}
compose_file=${COMPOSE_FILE:-docker-compose.yml}
compose_override_file=${COMPOSE_OVERRIDE_FILE:-}
compose_env_file=${COMPOSE_ENV_FILE:-}
db_service=${DB_SERVICE:-db}

case "$backup_stem" in
  ''|*[!A-Za-z0-9._-]*)
    printf 'BACKUP_STEM에는 영문자, 숫자, 점, 밑줄, 하이픈만 사용할 수 있습니다.\n' >&2
    exit 1
    ;;
esac
case "$backup_timeout_seconds" in
  ''|*[!0-9]*)
    printf 'BACKUP_TIMEOUT_SECONDS는 양의 정수여야 합니다.\n' >&2
    exit 1
    ;;
esac
test "$backup_timeout_seconds" -gt 0

mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
temporary_file=$(mktemp "$backup_dir/.admission_${timestamp}.dump.XXXXXX")
temporary_checksum=$(mktemp "$backup_dir/.admission_${timestamp}.sha256.XXXXXX")
temporary_manifest=$(mktemp "$backup_dir/.admission_${timestamp}.manifest.XXXXXX")
completed=0
backup_created=0
checksum_created=0
manifest_created=0
cleanup() {
  rm -f "$temporary_file"
  rm -f "$temporary_checksum"
  rm -f "$temporary_manifest"
  if [ "$completed" -ne 1 ]; then
    if [ "$backup_created" -eq 1 ]; then
      rm -f "$backup_file"
    fi
    if [ "$checksum_created" -eq 1 ]; then
      rm -f "$checksum_file"
    fi
    if [ "$manifest_created" -eq 1 ]; then
      rm -f "$manifest_file"
    fi
  fi
}
trap cleanup EXIT HUP INT TERM

set -- "$docker_bin" compose -f "$compose_file"
if [ -n "$compose_override_file" ]; then
  set -- "$@" -f "$compose_override_file"
fi
if [ -n "$compose_env_file" ]; then
  set -- "$@" --env-file "$compose_env_file"
fi

source_head_before=$("$timeout_bin" "$backup_timeout_seconds" "$@" exec -T "$db_service" sh -c \
  'psql -X --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --tuples-only --no-align --set ON_ERROR_STOP=1 --command "SELECT version_num FROM alembic_version"')
case "$source_head_before" in
  ''|*[!0-9a-f]*)
    printf '원본 DB Alembic head 형식이 유효하지 않습니다.\n' >&2
    exit 1
    ;;
esac

"$timeout_bin" "$backup_timeout_seconds" "$@" exec -T "$db_service" sh -c \
  'pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom --no-password --lock-wait-timeout=10s' > "$temporary_file"
test -s "$temporary_file"

source_head_after=$("$timeout_bin" "$backup_timeout_seconds" "$@" exec -T "$db_service" sh -c \
  'psql -X --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --tuples-only --no-align --set ON_ERROR_STOP=1 --command "SELECT version_num FROM alembic_version"')
if [ "$source_head_before" != "$source_head_after" ]; then
  printf '백업 중 Alembic head가 변경되어 archive를 폐기합니다.\n' >&2
  exit 1
fi

archive_listing=$("$timeout_bin" "$backup_timeout_seconds" "$@" exec -T "$db_service" \
  pg_restore --list < "$temporary_file")
table_data_entries=$(printf '%s\n' "$archive_listing" | awk '/ TABLE DATA / { count += 1 } END { print count + 0 }')
test "$table_data_entries" -gt 0

if ! ln "$temporary_file" "$backup_file"; then
  printf '동일한 이름의 백업 archive가 이미 존재합니다.\n' >&2
  exit 1
fi
backup_created=1
rm -f "$temporary_file"
(
  cd "$backup_dir"
  sha256sum "$(basename "$backup_file")"
) > "$temporary_checksum"
if ! ln "$temporary_checksum" "$checksum_file"; then
  printf '동일한 이름의 체크섬이 이미 존재합니다.\n' >&2
  exit 1
fi
checksum_created=1
rm -f "$temporary_checksum"
archive_digest=$(sha256sum "$backup_file" | awk '{print $1}')
{
  printf 'manifest_version=1\n'
  printf 'archive_basename=%s\n' "$(basename "$backup_file")"
  printf 'archive_sha256=%s\n' "$archive_digest"
  printf 'source_migration_head=%s\n' "$source_head_before"
  printf 'table_data_entries=%s\n' "$table_data_entries"
} > "$temporary_manifest"
if ! ln "$temporary_manifest" "$manifest_file"; then
  printf '동일한 이름의 manifest가 이미 존재합니다.\n' >&2
  exit 1
fi
manifest_created=1
rm -f "$temporary_manifest"
completed=1
trap - EXIT HUP INT TERM
printf 'PostgreSQL 백업 생성: %s\n' "$backup_file"
printf 'PostgreSQL 백업 체크섬: %s\n' "$checksum_file"
printf 'PostgreSQL 백업 manifest: %s\n' "$manifest_file"
