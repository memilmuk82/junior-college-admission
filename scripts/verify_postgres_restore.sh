#!/usr/bin/env sh
set -eu

backup_file=${BACKUP_FILE:?BACKUP_FILE must be set}
docker_bin=${DOCKER_BIN:-docker}
postgres_image=${POSTGRES_IMAGE:?POSTGRES_IMAGE must be an immutable image ID}
python_bin=${PYTHON_BIN:-.venv/bin/python}
timeout_bin=${TIMEOUT_BIN:-timeout}
restore_timeout_seconds=${RESTORE_TIMEOUT_SECONDS:-600}
restore_tmpfs_size_mb=${RESTORE_TMPFS_SIZE_MB:-512}
require_repository_head_match=${REQUIRE_REPOSITORY_HEAD_MATCH:-0}
expected_synthetic_sentinel_id=${EXPECTED_SYNTHETIC_SENTINEL_ID:-}
expected_synthetic_sentinel_name=${EXPECTED_SYNTHETIC_SENTINEL_NAME:-}
container_name="admission-restore-verify-$$"
container_id=""

case "$postgres_image" in
  sha256:*) ;;
  *)
    printf 'POSTGRES_IMAGE에는 sha256 image ID가 필요합니다.\n' >&2
    exit 1
    ;;
esac
image_digest=${postgres_image#sha256:}
case "$image_digest" in
  ''|*[!0-9a-f]*)
    printf 'POSTGRES_IMAGE sha256 형식이 유효하지 않습니다.\n' >&2
    exit 1
    ;;
esac
test "${#image_digest}" -eq 64

case "$restore_timeout_seconds" in
  ''|*[!0-9]*)
    printf 'RESTORE_TIMEOUT_SECONDS는 양의 정수여야 합니다.\n' >&2
    exit 1
    ;;
esac
test "$restore_timeout_seconds" -gt 0
case "$restore_tmpfs_size_mb" in
  ''|*[!0-9]*)
    printf 'RESTORE_TMPFS_SIZE_MB는 양의 정수여야 합니다.\n' >&2
    exit 1
    ;;
esac
test "$restore_tmpfs_size_mb" -gt 0
case "$require_repository_head_match" in
  0|1) ;;
  *)
    printf 'REQUIRE_REPOSITORY_HEAD_MATCH는 0 또는 1이어야 합니다.\n' >&2
    exit 1
    ;;
esac

test -f "$backup_file"
test -s "$backup_file"
test -f "$backup_file.sha256"
test -f "$backup_file.manifest"
backup_basename=$(basename "$backup_file")
actual_digest=$(sha256sum "$backup_file" | awk '{print $1}')
test "$(wc -l < "$backup_file.sha256" | tr -d ' ')" -eq 1
test "$(cat "$backup_file.sha256")" = "$actual_digest  $backup_basename"
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

repository_head=$("$python_bin" -m scripts.migration_head)
case "$repository_head" in
  *[!0-9a-f]*)
    printf 'Alembic head 형식이 유효하지 않습니다.\n' >&2
    exit 1
    ;;
esac
if [ "$require_repository_head_match" -eq 1 ] && [ "$source_head" != "$repository_head" ]; then
  printf '백업 원본과 저장소의 Alembic head가 일치하지 않습니다.\n' >&2
  exit 1
fi

cleanup() {
  if [ -n "$container_id" ]; then
    "$timeout_bin" 30 "$docker_bin" rm -f "$container_id" > /dev/null 2>&1 || true
  fi
}
trap cleanup EXIT HUP INT TERM

container_id=$("$timeout_bin" "$restore_timeout_seconds" "$docker_bin" run --detach \
  --name "$container_name" \
  --network none \
  --pull never \
  --pids-limit 128 \
  --memory 768m \
  --cpus 1 \
  --security-opt no-new-privileges:true \
  --tmpfs "/var/lib/postgresql/data:rw,noexec,nosuid,size=${restore_tmpfs_size_mb}m" \
  --env POSTGRES_HOST_AUTH_METHOD=trust \
  --env POSTGRES_DB=restore_verify \
  "$postgres_image")

ready=0
attempt=0
while [ "$attempt" -lt 30 ]; do
  if "$timeout_bin" 10 "$docker_bin" exec "$container_id" sh -c \
    'test "$(head -n 1 /var/lib/postgresql/data/postmaster.pid)" = "1"' > /dev/null 2>&1 \
    && "$timeout_bin" 10 "$docker_bin" exec "$container_id" pg_isready --username postgres --dbname restore_verify > /dev/null 2>&1; then
    ready=1
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  printf '격리 PostgreSQL 준비 시간 초과\n' >&2
  exit 1
fi

archive_listing=$("$timeout_bin" "$restore_timeout_seconds" "$docker_bin" exec -i \
  "$container_id" pg_restore --list < "$backup_file")
actual_table_data_entries=$(printf '%s\n' "$archive_listing" | \
  awk '/ TABLE DATA / { count += 1 } END { print count + 0 }')
if [ "$actual_table_data_entries" -ne "$table_data_entries" ]; then
  printf 'archive TABLE DATA 항목 수가 manifest와 일치하지 않습니다.\n' >&2
  exit 1
fi

"$timeout_bin" "$restore_timeout_seconds" "$docker_bin" exec -i "$container_id" pg_restore \
  --username postgres \
  --dbname restore_verify \
  --exit-on-error \
  --no-owner \
  --no-privileges < "$backup_file"

restored_head=$("$timeout_bin" "$restore_timeout_seconds" "$docker_bin" exec "$container_id" psql \
  --username postgres \
  --dbname restore_verify \
  --tuples-only \
  --no-align \
  --set ON_ERROR_STOP=1 \
  --command 'SELECT version_num FROM alembic_version')

if [ "$restored_head" != "$source_head" ]; then
  printf '복원 DB와 백업 원본의 Alembic head가 일치하지 않습니다.\n' >&2
  exit 1
fi

if [ -n "$expected_synthetic_sentinel_id" ]; then
  case "$expected_synthetic_sentinel_id" in
    *[!0-9a-f-]*)
      printf '합성 sentinel ID 형식이 유효하지 않습니다.\n' >&2
      exit 1
      ;;
  esac
  test "${#expected_synthetic_sentinel_id}" -eq 36
  canonical_synthetic_sentinel_name="Synthetic backup restore sentinel $expected_synthetic_sentinel_id"
  if [ "$expected_synthetic_sentinel_name" != "$canonical_synthetic_sentinel_name" ]; then
    printf '합성 sentinel 이름이 검증된 ID와 일치하지 않습니다.\n' >&2
    exit 1
  fi
  sentinel_count=$("$timeout_bin" "$restore_timeout_seconds" "$docker_bin" exec "$container_id" psql \
    --username postgres \
    --dbname restore_verify \
    --tuples-only \
    --no-align \
    --set ON_ERROR_STOP=1 \
    --command "SELECT count(*) FROM institutions WHERE id = '$expected_synthetic_sentinel_id' AND name = '$expected_synthetic_sentinel_name' AND institution_type = 'SYNTHETIC'")
  if [ "$sentinel_count" != "1" ]; then
    printf '합성 데이터 sentinel 복원 검증에 실패했습니다.\n' >&2
    exit 1
  fi
fi

table_count=$("$timeout_bin" "$restore_timeout_seconds" "$docker_bin" exec "$container_id" psql \
  --username postgres \
  --dbname restore_verify \
  --tuples-only \
  --no-align \
  --set ON_ERROR_STOP=1 \
  --command "SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname = 'public'")
test "$table_count" -gt 0
test "$table_count" -ge "$table_data_entries"

printf '격리 PostgreSQL 복원 검증 통과: source_migration=%s, repository_migration=%s, public_tables=%s\n' \
  "$restored_head" "$repository_head" "$table_count"
