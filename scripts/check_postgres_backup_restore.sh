#!/usr/bin/env sh
set -eu

docker_bin=${DOCKER_BIN:-docker}
compose_file=${COMPOSE_FILE:-docker-compose.yml}
compose_override_file=${COMPOSE_OVERRIDE_FILE:-}
compose_env_file=${COMPOSE_ENV_FILE:-}
db_service=${DB_SERVICE:-db-test}
backup_dir=$(mktemp -d /tmp/junior-college-admission-backup-test.XXXXXX)
sentinel_id=$(cat /proc/sys/kernel/random/uuid)
sentinel_name="Synthetic backup restore sentinel $sentinel_id"
case "$sentinel_id" in
  *[!0-9a-f-]*) exit 1 ;;
esac
test "${#sentinel_id}" -eq 36

cleanup() {
  case "$backup_dir" in
    /tmp/junior-college-admission-backup-test.*)
      rm -rf "$backup_dir"
      ;;
  esac
}
trap cleanup EXIT HUP INT TERM

set -- "$docker_bin" compose -f "$compose_file"
if [ -n "$compose_override_file" ]; then
  set -- "$@" -f "$compose_override_file"
fi
if [ -n "$compose_env_file" ]; then
  set -- "$@" --env-file "$compose_env_file"
fi

"$@" exec -T "$db_service" sh -c \
  "psql -X --username \"\$POSTGRES_USER\" --dbname \"\$POSTGRES_DB\" --set ON_ERROR_STOP=1 --command \"INSERT INTO institutions (id, name, institution_type) VALUES ('$sentinel_id', '$sentinel_name', 'SYNTHETIC')\"" > /dev/null
image_ref=$("$@" images -q "$db_service")
test -n "$image_ref"
image_id=$("$docker_bin" image inspect --format '{{.Id}}' "$image_ref")
test -n "$image_id"

DOCKER_BIN="$docker_bin" \
COMPOSE_FILE="$compose_file" \
COMPOSE_OVERRIDE_FILE="$compose_override_file" \
COMPOSE_ENV_FILE="$compose_env_file" \
DB_SERVICE="$db_service" \
BACKUP_DIR="$backup_dir" \
  ./scripts/backup_postgres.sh > /dev/null

set -- "$backup_dir"/*.dump
test "$#" -eq 1
backup_file=$1

DOCKER_BIN="$docker_bin" \
COMPOSE_FILE="$compose_file" \
COMPOSE_OVERRIDE_FILE="$compose_override_file" \
COMPOSE_ENV_FILE="$compose_env_file" \
DB_SERVICE="$db_service" \
BACKUP_FILE="$backup_file" \
  ./scripts/verify_postgres_backup.sh > /dev/null

DOCKER_BIN="$docker_bin" \
POSTGRES_IMAGE="$image_id" \
BACKUP_FILE="$backup_file" \
REQUIRE_REPOSITORY_HEAD_MATCH=1 \
EXPECTED_SYNTHETIC_SENTINEL_ID="$sentinel_id" \
EXPECTED_SYNTHETIC_SENTINEL_NAME="$sentinel_name" \
  ./scripts/verify_postgres_restore.sh > /dev/null

printf '합성 PostgreSQL 백업·격리 복원 검증 통과\n'
