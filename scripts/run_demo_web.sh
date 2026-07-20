#!/bin/sh
set -eu

if [ "${APP_ENV:-}" != "demo-sandbox" ] || [ "${DEMO_SANDBOX_ENABLED:-}" != "true" ]; then
  echo "demo 전용 실행 조건이 충족되지 않았습니다." >&2
  exit 1
fi

required_secret_file() {
  variable_name="$1"
  eval "secret_path=\${$variable_name:-}"
  if [ -z "$secret_path" ] || [ ! -f "$secret_path" ] || [ ! -s "$secret_path" ]; then
    echo "demo 전용 secret 파일이 누락되었습니다: $variable_name" >&2
    exit 1
  fi
}

for variable_name in \
  SECRET_KEY_FILE \
  DATABASE_URL_FILE \
  BYOK_MASTER_KEY_FILE \
  DEMO_SANDBOX_PUBLIC_PASSWORD_FILE
do
  required_secret_file "$variable_name"
done

database_url=$(tr -d '\r\n' < "$DATABASE_URL_FILE")
case "$database_url" in
  postgresql://*'@db-demo:5432/'*|postgresql+psycopg://*'@db-demo:5432/'*) ;;
  *)
    echo "demo DB URL은 db-demo 전용 호스트만 사용할 수 있습니다." >&2
    exit 1
    ;;
esac
unset database_url

flask --app wsgi db upgrade
flask --app wsgi demo-sandbox bootstrap

cleanup_loop() {
  while :; do
    flask --app wsgi purge-expired-anonymous-calculations --max-age-seconds 1800 \
      || echo "demo anonymous cleanup failed; retrying in 300 seconds" >&2
    flask --app wsgi demo-sandbox purge-session-ai --max-age-seconds 21600 \
      || echo "demo session AI cleanup failed; retrying in 300 seconds" >&2
    sleep 300
  done
}

cleanup_loop &
cleanup_pid=$!

terminate() {
  kill "$cleanup_pid" 2>/dev/null || true
  if [ -n "${web_pid:-}" ]; then
    kill "$web_pid" 2>/dev/null || true
  fi
}
trap terminate INT TERM EXIT

gunicorn \
  --bind=0.0.0.0:5000 \
  --workers="${DEMO_WEB_WORKERS:-1}" \
  --threads="${DEMO_WEB_THREADS:-4}" \
  --timeout=30 \
  --graceful-timeout=30 \
  --access-logfile=- \
  --access-logformat='%(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s' \
  --error-logfile=- \
  wsgi:app &
web_pid=$!
wait "$web_pid"
