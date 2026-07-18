#!/bin/sh
set -eu

flask --app wsgi db upgrade
case "${PRODUCTION_BOOTSTRAP_ADMIN_ON_STARTUP:-1}" in
  1)
    flask --app wsgi auth bootstrap-admin
    flask --app wsgi auth bootstrap-demo
    ;;
  0) ;;
  *) exit 1 ;;
esac

cleanup_loop() {
  while :; do
    flask --app wsgi purge-expired-anonymous-calculations --max-age-seconds 1800 \
      || echo "anonymous cleanup failed; retrying in 300 seconds" >&2
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
  --workers="${PRODUCTION_WEB_WORKERS:-2}" \
  --threads="${PRODUCTION_WEB_THREADS:-2}" \
  --timeout=30 \
  --graceful-timeout=30 \
  --access-logfile=- \
  --access-logformat='%(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s' \
  --error-logfile=- \
  wsgi:app &
web_pid=$!
wait "$web_pid"
