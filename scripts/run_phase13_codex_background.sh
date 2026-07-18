#!/usr/bin/env sh
set -eu
umask 077

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
prompt_file="$repo_root/tasks/PHASE_13.md"
run_root=${PHASE13_RUN_DIR:-/tmp/junior-college-admission-phase13}
active_pid_file="$run_root/active.pid"
latest_run_file="$run_root/latest_run"

command -v codex >/dev/null 2>&1 || {
  printf 'codex CLI를 찾을 수 없습니다. PATH와 설치 상태를 확인하세요.\n' >&2
  exit 1
}
command -v git >/dev/null 2>&1 || {
  printf 'git을 찾을 수 없습니다.\n' >&2
  exit 1
}
test -f "$prompt_file" || {
  printf 'Phase 13 프롬프트를 찾을 수 없습니다: %s\n' "$prompt_file" >&2
  exit 1
}
git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  printf '저장소 경로가 유효한 Git worktree가 아닙니다: %s\n' "$repo_root" >&2
  exit 1
}

mkdir -p "$run_root"
chmod 700 "$run_root"

if [ -f "$active_pid_file" ]; then
  active_pid=$(sed -n '1p' "$active_pid_file")
  case "$active_pid" in
    ''|*[!0-9]*) active_pid=0 ;;
  esac
  if [ "$active_pid" -gt 0 ] && kill -0 "$active_pid" 2>/dev/null; then
    printf 'Phase 13 Codex 작업이 이미 실행 중입니다. PID: %s\n' "$active_pid" >&2
    printf '기존 로그 위치는 %s 아래에서 확인하세요.\n' "$run_root" >&2
    exit 1
  fi
fi

run_timestamp=$(date +%Y%m%d_%H%M%S)
run_dir="$run_root/${run_timestamp}_$$"
log_file="$run_dir/codex.log"
final_file="$run_dir/final.md"
pid_file="$run_dir/pid"

mkdir -p "$run_dir"
chmod 700 "$run_dir"

set -- codex \
  -C "$repo_root" \
  --sandbox danger-full-access \
  --ask-for-approval never \
  -c agents.max_threads=3 \
  -c agents.max_depth=1

if [ -n "${CODEX_MODEL:-}" ]; then
  set -- "$@" --model "$CODEX_MODEL"
fi

set -- "$@" exec --output-last-message "$final_file" -

nohup "$@" < "$prompt_file" > "$log_file" 2>&1 &
run_pid=$!

printf '%s\n' "$run_pid" > "$pid_file"
printf '%s\n' "$run_pid" > "$active_pid_file"
printf '%s\n' "$run_dir" > "$latest_run_file"

printf 'Phase 13 Codex 백그라운드 작업을 시작했습니다.\n'
printf 'PID: %s\n' "$run_pid"
printf '로그: %s\n' "$log_file"
printf '최종 결과: %s\n' "$final_file"
printf '진행 확인: tail -f %s\n' "$log_file"
printf '최근 실행 경로: %s\n' "$latest_run_file"
