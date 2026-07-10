from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_SUFFIXES = {
    ".csv",
    ".db",
    ".jpeg",
    ".jpg",
    ".ods",
    ".pdf",
    ".png",
    ".sqlite",
    ".sqlite3",
    ".tif",
    ".tiff",
    ".tsv",
    ".webp",
    ".xls",
    ".xlsm",
    ".xlsx",
}
PUBLIC_SEED_SUFFIXES = {".csv", ".tsv"}
PRIVATE_PREFIXES = ("data/raw/", "data/staging/", "data/published/", "instance/", "uploads/")
KEY_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"(?:OPENAI|GEMINI|ANTHROPIC)_API_KEY[ \t]*=[ \t]*[^\s#]+"),
)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def inspect(paths: list[Path]) -> list[str]:
    violations: list[str] = []
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        if relative == ".env" or (relative.startswith(".env.") and relative != ".env.example"):
            violations.append(f"환경 파일: {relative}")
        if relative.startswith(PRIVATE_PREFIXES):
            violations.append(f"비공개 데이터 경로: {relative}")
        suffix = path.suffix.lower()
        is_public_seed = relative.startswith("data/seed/") and suffix in PUBLIC_SEED_SUFFIXES
        if suffix in BLOCKED_SUFFIXES and not is_public_seed:
            violations.append(f"차단된 파일 형식: {relative}")
        if not path.is_file() or (suffix in BLOCKED_SUFFIXES and not is_public_seed):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in KEY_PATTERNS:
            if pattern.search(content):
                violations.append(f"API 키 의심 문자열: {relative}")
                break
    return violations


def main() -> int:
    violations = inspect(tracked_files())
    if violations:
        print("민감자료 검사 실패")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print("민감자료 검사 통과: Git 포함 대상에서 차단 파일과 API 키를 찾지 못했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
