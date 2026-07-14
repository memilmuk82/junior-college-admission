#!/usr/bin/env sh
set -eu

docker_bin=${DOCKER_BIN:-docker}
timeout_bin=${TIMEOUT_BIN:-timeout}
metrics_timeout_seconds=${METRICS_TIMEOUT_SECONDS:-60}
metrics_db_user=${METRICS_DB_USER:-}
require_metrics_db_user=${REQUIRE_METRICS_DB_USER:-0}
compose_file=${COMPOSE_FILE:-docker-compose.yml}
compose_override_file=${COMPOSE_OVERRIDE_FILE:-}
compose_env_file=${COMPOSE_ENV_FILE:-}
db_service=${DB_SERVICE:-db}
metrics_sql=${METRICS_SQL:-deploy/postgres_metrics_readonly.sql}

test -f "$metrics_sql"
case "$metrics_timeout_seconds" in
  ''|*[!0-9]*)
    printf 'METRICS_TIMEOUT_SECONDS는 양의 정수여야 합니다.\n' >&2
    exit 1
    ;;
esac
test "$metrics_timeout_seconds" -gt 0
case "$metrics_db_user" in
  *[!A-Za-z0-9_.-]*)
    printf 'METRICS_DB_USER 형식이 유효하지 않습니다.\n' >&2
    exit 1
    ;;
esac
case "$require_metrics_db_user" in
  0|1) ;;
  *)
    printf 'REQUIRE_METRICS_DB_USER는 0 또는 1이어야 합니다.\n' >&2
    exit 1
    ;;
esac
if [ "$require_metrics_db_user" -eq 1 ] && [ -z "$metrics_db_user" ]; then
  printf '운영 지표 수집에는 최소권한 METRICS_DB_USER가 필요합니다.\n' >&2
  exit 1
fi

set -- "$docker_bin" compose -f "$compose_file"
if [ -n "$compose_override_file" ]; then
  set -- "$@" -f "$compose_override_file"
fi
if [ -n "$compose_env_file" ]; then
  set -- "$@" --env-file "$compose_env_file"
fi

if [ -n "$metrics_db_user" ]; then
  set -- "$@" exec -T --env "METRICS_DB_USER=$metrics_db_user" "$db_service"
else
  set -- "$@" exec -T "$db_service"
fi

"$timeout_bin" "$metrics_timeout_seconds" "$@" sh -c \
  'psql -X --username "${METRICS_DB_USER:-$POSTGRES_USER}" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 --file -' < "$metrics_sql"
