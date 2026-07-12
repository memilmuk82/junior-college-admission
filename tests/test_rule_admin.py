from decimal import Decimal

from app.services.rule_admin import compare_rule_impact, compare_rule_payloads


def test_payload_comparison_reports_exact_nested_paths_without_free_formula() -> None:
    before = {"weights": {"grade_1": "0.30", "grade_3": "0.40"}, "rounding": "FINAL"}
    after = {"weights": {"grade_1": "0.25", "grade_3": "0.45"}, "rounding": "FINAL"}

    changes = compare_rule_payloads(before, after)

    assert [(change.path, change.before, change.after) for change in changes] == [
        ("weights.grade_1", "0.30", "0.25"),
        ("weights.grade_3", "0.40", "0.45"),
    ]


def test_impact_comparison_uses_only_named_synthetic_samples() -> None:
    samples = (
        {"sample_id": "synthetic-a", "grade": "2"},
        {"sample_id": "synthetic-b", "grade": "4"},
    )

    def evaluator(payload: dict[str, object], sample: dict[str, str]) -> Decimal:
        return Decimal(str(payload["base"])) - Decimal(sample["grade"]) * Decimal(
            str(payload["multiplier"])
        )

    impacts = compare_rule_impact(
        {"base": "100", "multiplier": "10"},
        {"base": "100", "multiplier": "12"},
        samples,
        evaluator,
    )

    assert [(item.sample_id, item.before, item.after, item.delta) for item in impacts] == [
        ("synthetic-a", Decimal("80"), Decimal("76"), Decimal("-4")),
        ("synthetic-b", Decimal("60"), Decimal("52"), Decimal("-8")),
    ]
