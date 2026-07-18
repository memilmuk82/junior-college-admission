#!/usr/bin/env sh
set -eu
umask 077

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
prompt_file="$repo_root/tasks/PHASE_14_CORE_WORKFLOW_REBUILD.md"
reference_xlsx="$repo_root/tmp/codex-reference/xlsx/OOO_2026 전문대 수시 분석_2027 수도권 전문대 입결_전문대교협.xlsx"
expected_xlsx_digest=bde8fe5d513ce2737c08815b0d7e1df366dc8844e6ff7f243eccb63c3bd40606
run_root=${PHASE14_RUN_DIR:-/tmp/junior-college-admission-phase14}
lock_file="$run_root/run.lock"
active_pid_file="$run_root/active.pid"
latest_run_file="$run_root/latest_run"

write_status() {
  status_value=$1
  status_target=$2
  status_temp="$status_target.tmp.$$"
  printf '%s\n' "$status_value" > "$status_temp"
  mv "$status_temp" "$status_target"
}

supervise() {
  run_dir=$1
  log_file="$run_dir/codex.log"
  events_file="$run_dir/events.jsonl"
  final_file="$run_dir/final.md"
  status_file="$run_dir/status"
  exit_code_file="$run_dir/exit_code"
  heartbeat_file="$run_dir/heartbeat"
  codex_pid_file="$run_dir/codex.pid"

  exec 9>"$lock_file"
  if ! flock -n 9; then
    write_status "BLOCKED_ALREADY_RUNNING" "$status_file"
    exit 1
  fi

  printf '%s\n' "$$" > "$active_pid_file"
  write_status "RUNNING" "$status_file"

  set -- codex \
    --strict-config \
    -C "$repo_root" \
    --sandbox danger-full-access \
    --ask-for-approval never \
    -c agents.max_threads=4 \
    -c agents.max_depth=1

  if [ -n "${CODEX_MODEL:-}" ]; then
    set -- "$@" --model "$CODEX_MODEL"
  fi

  set -- "$@" exec --json --output-last-message "$final_file" -

  "$@" < "$prompt_file" > "$events_file" 2> "$log_file" &
  codex_pid=$!
  printf '%s\n' "$codex_pid" > "$codex_pid_file"

  (
    while kill -0 "$codex_pid" 2>/dev/null; do
      heartbeat_temp="$heartbeat_file.tmp.$$"
      {
        printf 'updated_at=%s\n' "$(date -Iseconds)"
        printf 'codex_pid=%s\n' "$codex_pid"
        printf 'events_bytes=%s\n' "$(wc -c < "$events_file" 2>/dev/null || printf 0)"
        printf 'log_bytes=%s\n' "$(wc -c < "$log_file" 2>/dev/null || printf 0)"
      } > "$heartbeat_temp"
      mv "$heartbeat_temp" "$heartbeat_file"
      sleep 30
    done
  ) &
  heartbeat_pid=$!

  set +e
  wait "$codex_pid"
  codex_exit=$?
  set -e

  kill "$heartbeat_pid" 2>/dev/null || true
  wait "$heartbeat_pid" 2>/dev/null || true
  printf '%s\n' "$codex_exit" > "$exit_code_file"

  if [ "$codex_exit" -eq 0 ] && [ -s "$final_file" ]; then
    write_status "COMPLETED_AGENT_RUN" "$status_file"
  else
    write_status "FAILED_AGENT_RUN" "$status_file"
  fi

  if [ "$(sed -n '1p' "$active_pid_file" 2>/dev/null || true)" = "$$" ]; then
    rm -f "$active_pid_file"
  fi
  exit "$codex_exit"
}

if [ "${1:-}" = "--supervise" ]; then
  test "$#" -eq 2 || {
    printf '내부 supervisor 실행 인자가 올바르지 않습니다.\n' >&2
    exit 2
  }
  supervise "$2"
fi

for required_command in codex git sha256sum flock setsid; do
  command -v "$required_command" >/dev/null 2>&1 || {
    printf '%s 명령을 찾을 수 없습니다.\n' "$required_command" >&2
    exit 1
  }
done

test -f "$prompt_file" || {
  printf 'Phase 14 프롬프트를 찾을 수 없습니다: %s\n' "$prompt_file" >&2
  exit 1
}
test -f "$reference_xlsx" || {
  printf '기준 XLSX를 찾을 수 없습니다: %s\n' "$reference_xlsx" >&2
  exit 1
}
git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
  printf '저장소 경로가 유효한 Git worktree가 아닙니다: %s\n' "$repo_root" >&2
  exit 1
}

actual_xlsx_digest=$(sha256sum "$reference_xlsx" | awk '{print $1}')
if [ "$actual_xlsx_digest" != "$expected_xlsx_digest" ]; then
  printf '기준 XLSX digest가 예상값과 다릅니다. 실행을 중단합니다.\n' >&2
  printf 'expected=%s\n' "$expected_xlsx_digest" >&2
  printf 'actual=%s\n' "$actual_xlsx_digest" >&2
  exit 1
fi

codex --version >/dev/null
git -C "$repo_root" status --short >/dev/null

mkdir -p "$run_root"
chmod 700 "$run_root"

if [ -f "$active_pid_file" ]; then
  active_pid=$(sed -n '1p' "$active_pid_file")
  case "$active_pid" in
    ''|*[!0-9]*) active_pid=0 ;;
  esac
  if [ "$active_pid" -gt 0 ] && kill -0 "$active_pid" 2>/dev/null; then
    printf 'Phase 14 Codex 작업이 이미 실행 중입니다. supervisor PID: %s\n' "$active_pid" >&2
    printf '최근 실행 경로: %s\n' "$(sed -n '1p' "$latest_run_file" 2>/dev/null || true)" >&2
    exit 1
  fi
fi

run_timestamp=$(date +%Y%m%d_%H%M%S)
run_dir="$run_root/${run_timestamp}_$$"
final_file="$run_dir/final.md"
status_file="$run_dir/status"
metadata_file="$run_dir/metadata.txt"
supervisor_pid_file="$run_dir/supervisor.pid"

mkdir -p "$run_dir"
chmod 700 "$run_dir"

start_head=$(git -C "$repo_root" rev-parse HEAD)
prompt_digest=$(sha256sum "$prompt_file" | awk '{print $1}')
{
  printf 'started_at=%s\n' "$(date -Iseconds)"
  printf 'timezone=Asia/Seoul\n'
  printf 'repo_root=%s\n' "$repo_root"
  printf 'start_head=%s\n' "$start_head"
  printf 'prompt_sha256=%s\n' "$prompt_digest"
  printf 'reference_xlsx_sha256=%s\n' "$actual_xlsx_digest"
  printf 'branch=%s\n' "$(git -C "$repo_root" branch --show-current)"
  printf 'codex_version=%s\n' "$(codex --version 2>/dev/null)"
} > "$metadata_file"

write_status "STARTING" "$status_file"
printf '%s\n' "$run_dir" > "$latest_run_file"

setsid nohup "$0" --supervise "$run_dir" >/dev/null 2>&1 &
supervisor_pid=$!
printf '%s\n' "$supervisor_pid" > "$supervisor_pid_file"

launch_checks=0
while [ "$launch_checks" -lt 20 ]; do
  if [ -f "$run_dir/codex.pid" ] || [ "$(sed -n '1p' "$status_file" 2>/dev/null || true)" = "BLOCKED_ALREADY_RUNNING" ]; then
    break
  fi
  launch_checks=$((launch_checks + 1))
  sleep 1
done

current_status=$(sed -n '1p' "$status_file" 2>/dev/null || true)
if [ "$current_status" = "BLOCKED_ALREADY_RUNNING" ] || ! kill -0 "$supervisor_pid" 2>/dev/null; then
  printf 'Phase 14 supervisor가 시작되지 않았습니다. 상태: %s\n' "$current_status" >&2
  exit 1
fi

printf 'Phase 14 핵심 업무 전면 재구축 작업을 백그라운드로 시작했습니다.\n'
printf 'Supervisor PID: %s\n' "$supervisor_pid"
printf 'Codex PID: %s\n' "$(sed -n '1p' "$run_dir/codex.pid")"
printf '상태: %s\n' "$status_file"
printf '이벤트: %s\n' "$run_dir/events.jsonl"
printf '오류 로그: %s\n' "$run_dir/codex.log"
printf '최종 결과: %s\n' "$final_file"
printf 'Heartbeat: %s\n' "$run_dir/heartbeat"
printf '메타데이터: %s\n' "$metadata_file"
printf '최근 실행 경로: %s\n' "$latest_run_file"
