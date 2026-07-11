from pathlib import Path

from scripts.validate_rules import inspect_rule_seeds, validate_rule


def test_published_rule_without_human_evidence_is_rejected() -> None:
    violations = validate_rule(
        {"lifecycle_status": "PUBLISHED", "independent_verified": False},
        Path("synthetic-rule.json"),
    )

    assert len(violations) == 4


def test_empty_rule_seed_directory_is_valid(tmp_path: Path) -> None:
    assert inspect_rule_seeds(tmp_path) == []
