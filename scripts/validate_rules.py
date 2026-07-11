from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RULE_SEED_ROOT = ROOT / "data" / "seed" / "rules"
PUBLISHED_REQUIRED_FIELDS = (
    "source_citation_id",
    "golden_test_ref",
    "human_approved_at",
)


def validate_rule(rule: dict[str, Any], source: Path) -> list[str]:
    if rule.get("lifecycle_status") != "PUBLISHED":
        return []

    violations = [
        f"{source}: PUBLISHED 규칙의 {field} 누락"
        for field in PUBLISHED_REQUIRED_FIELDS
        if not rule.get(field)
    ]
    if rule.get("independent_verified") is not True:
        violations.append(f"{source}: PUBLISHED 규칙의 독립 검증 누락")
    return violations


def inspect_rule_seeds(root: Path = RULE_SEED_ROOT) -> list[str]:
    violations: list[str] = []
    for path in sorted(root.glob("**/*.json")) if root.exists() else []:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            violations.append(f"{path}: JSON 읽기 실패 ({error})")
            continue
        rules = payload if isinstance(payload, list) else [payload]
        for rule in rules:
            if not isinstance(rule, dict):
                violations.append(f"{path}: 규칙은 JSON 객체여야 함")
                continue
            violations.extend(validate_rule(rule, path))
    return violations


def main() -> int:
    violations = inspect_rule_seeds()
    if violations:
        print("규칙 검증 실패")
        for violation in violations:
            print(f"- {violation}")
        return 1
    print("규칙 검증 통과: 게시 규칙의 근거·검증·골든·사람 승인 계약을 확인했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
