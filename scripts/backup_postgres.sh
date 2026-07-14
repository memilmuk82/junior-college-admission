#!/usr/bin/env sh
set -eu
umask 077

backup_dir=${BACKUP_DIR:-backups}
timestamp=$(date +%Y%m%d_%H%M%S)
backup_file="$backup_dir/admission_$timestamp.dump"
temporary_file="$backup_file.tmp.$$"

mkdir -p "$backup_dir"
cleanup() {
  rm -f "$temporary_file"
}
trap cleanup EXIT HUP INT TERM

docker compose -f docker-compose.yml exec -T db sh -c 'pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom' > "$temporary_file"
test -s "$temporary_file"
mv "$temporary_file" "$backup_file"
trap - EXIT HUP INT TERM
printf 'PostgreSQL 백업 생성: %s\n' "$backup_file"
