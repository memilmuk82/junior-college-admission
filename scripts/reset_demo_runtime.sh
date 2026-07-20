#!/bin/sh
set -eu

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compose_file="$repository_root/docker-compose.demo.yml"
env_file="${DEMO_ENV_FILE:-$repository_root/.env.demo}"
demo_project_name=junior-college-admission-demo

if [ ! -f "$compose_file" ] || [ ! -f "$env_file" ]; then
  echo "demo compose 또는 전용 환경 파일을 찾을 수 없습니다." >&2
  exit 1
fi

# 이 고정 프로젝트의 DB volume과 tmpfs 컨테이너만 제거한다. 운영 compose와
# production_postgres_data/production_uploads에는 이름·프로젝트 모두 겹치지 않는다.
COMPOSE_PROJECT_NAME="$demo_project_name" docker compose \
  -f "$compose_file" \
  --env-file "$env_file" \
  down --volumes --remove-orphans --timeout 30

COMPOSE_PROJECT_NAME="$demo_project_name" docker compose \
  -f "$compose_file" \
  --env-file "$env_file" \
  up --detach --build --wait

echo "demo runtime 초기화 완료: 공개 seed와 기준 체험계정이 다시 생성되었습니다."
