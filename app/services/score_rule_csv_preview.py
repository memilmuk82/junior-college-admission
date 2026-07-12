from __future__ import annotations

from dataclasses import dataclass

from app.services.rule_admin import PayloadChange, compare_rule_payloads
from app.services.score_rule_schema import (
    CsvValidationIssue,
    ManagedScoreRule,
    parse_score_rule_csv,
    score_rule_to_payload,
)

type RuleBusinessKey = tuple[int, str, str, str, str]


class DraftSelectionError(ValueError):
    pass


@dataclass(frozen=True)
class ScoreRuleCsvPreviewItem:
    row_number: int
    rule: ManagedScoreRule
    classification: str
    current_rule: ManagedScoreRule | None
    changes: tuple[PayloadChange, ...]


@dataclass(frozen=True)
class ScoreRuleCsvPreview:
    items: tuple[ScoreRuleCsvPreviewItem, ...]
    issues: tuple[CsvValidationIssue, ...]


@dataclass(frozen=True)
class ScoreRuleDraftCandidate:
    rule: ManagedScoreRule
    lifecycle_status: str
    supersedes_rule_version: str | None
    auto_publish: bool


def build_score_rule_csv_preview(
    csv_data: bytes, current_rules: tuple[ManagedScoreRule, ...]
) -> ScoreRuleCsvPreview:
    parsed = parse_score_rule_csv(csv_data)
    existing: dict[RuleBusinessKey, list[ManagedScoreRule]] = {}
    for rule in current_rules:
        existing.setdefault(rule.identity.key, []).append(rule)
    items: list[ScoreRuleCsvPreviewItem] = []
    for row_number, rule in enumerate(parsed.rows, start=2):
        matches = existing.get(rule.identity.key, [])
        current = matches[0] if len(matches) == 1 else None
        changes: tuple[PayloadChange, ...] = ()
        if not matches:
            classification = "NEW"
        elif len(matches) > 1:
            classification = "CONFLICT"
        else:
            assert current is not None
            changes = compare_rule_payloads(_comparable(current), _comparable(rule))
            if not changes:
                classification = "UNCHANGED"
            elif rule.rule_version == current.rule_version:
                classification = "CONFLICT"
            else:
                classification = "CHANGED"
        items.append(ScoreRuleCsvPreviewItem(row_number, rule, classification, current, changes))
    return ScoreRuleCsvPreview(tuple(items), parsed.issues)


def prepare_selected_score_rule_drafts(
    preview: ScoreRuleCsvPreview, selected_keys: tuple[RuleBusinessKey, ...]
) -> tuple[ScoreRuleDraftCandidate, ...]:
    if not selected_keys or len(set(selected_keys)) != len(selected_keys):
        raise DraftSelectionError("중복 없는 유효 행을 하나 이상 선택해야 합니다.")
    by_key = {item.rule.identity.key: item for item in preview.items}
    drafts: list[ScoreRuleDraftCandidate] = []
    for key in selected_keys:
        item = by_key.get(key)
        if item is None or item.classification not in {"NEW", "CHANGED"}:
            raise DraftSelectionError("신규 또는 변경으로 검증된 행만 DRAFT로 준비할 수 있습니다.")
        drafts.append(
            ScoreRuleDraftCandidate(
                rule=item.rule,
                lifecycle_status="DRAFT",
                supersedes_rule_version=(
                    None if item.current_rule is None else item.current_rule.rule_version
                ),
                auto_publish=False,
            )
        )
    return tuple(drafts)


def _comparable(rule: ManagedScoreRule) -> dict[str, object]:
    return {
        **score_rule_to_payload(rule),
        "university_name": rule.university_name,
        "admission_track_name": rule.admission_track_name,
        "evidence_document_id": rule.evidence_document_id,
        "evidence_page": rule.evidence_page,
        "evidence_location": rule.evidence_location,
        "source_status": rule.source_status,
    }


__all__ = [
    "DraftSelectionError",
    "ScoreRuleCsvPreview",
    "ScoreRuleCsvPreviewItem",
    "ScoreRuleDraftCandidate",
    "build_score_rule_csv_preview",
    "prepare_selected_score_rule_drafts",
]
