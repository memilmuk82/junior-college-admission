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


def test_published_eligibility_rule_with_executable_expression_is_rejected() -> None:
    violations = validate_rule(
        {
            "rule_type": "ADMISSION_ELIGIBILITY",
            "lifecycle_status": "PUBLISHED",
            "source_citation_id": "synthetic-citation",
            "golden_test_ref": "synthetic-golden",
            "human_approved_at": "2026-07-12T00:00:00Z",
            "independent_verified": True,
            "rule_payload": {"expression": "student.school == 'GENERAL'"},
        },
        Path("synthetic-rule.json"),
    )

    assert len(violations) == 1
    assert "payload 오류" in violations[0]


def test_published_grade_scope_rule_with_unknown_policy_is_rejected() -> None:
    violations = validate_rule(
        {
            "rule_type": "GRADE_SOURCE_SCOPE",
            "lifecycle_status": "PUBLISHED",
            "source_citation_id": "synthetic-citation",
            "golden_test_ref": "synthetic-golden",
            "human_approved_at": "2026-07-12T00:00:00Z",
            "independent_verified": True,
            "rule_payload": {"schema_version": 1, "policy": "GUESSED_SCOPE"},
        },
        Path("synthetic-rule.json"),
    )

    assert len(violations) == 1
    assert "payload 오류" in violations[0]


def test_published_score_rule_with_free_formula_is_rejected() -> None:
    violations = validate_rule(
        {
            "rule_type": "SCORE_RULE",
            "lifecycle_status": "PUBLISHED",
            "source_citation_id": "synthetic-citation",
            "golden_test_ref": "synthetic-golden",
            "human_approved_at": "2026-07-12T00:00:00Z",
            "independent_verified": True,
            "rule_payload": {"formula": "eval-me"},
        },
        Path("synthetic-rule.json"),
    )

    assert len(violations) == 1
    assert "payload 오류" in violations[0]
