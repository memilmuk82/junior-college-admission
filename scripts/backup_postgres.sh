#!/usr/bin/env sh
set -eu

backup_dir=${BACKUP_DIR:-backups}
timestamp=$(date +%Y%m%d_%H%M%S)
backup_file="$backup_dir/admission_$timestamp.dump"

mkdir -p "$backup_dir"
docker compose -f docker-compose.yml exec -T db sh -c 'pg_dump --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --format=custom' > "$backup_file"
printf 'PostgreSQL 백업 생성: %s\n' "$backup_file"
