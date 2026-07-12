from dataclasses import replace
from decimal import Decimal

import pytest

from app.services.score_rule_csv_preview import (
    DraftSelectionError,
    build_score_rule_csv_preview,
    prepare_selected_score_rule_drafts,
)
from app.services.score_rule_schema import parse_score_rule_csv, write_score_rule_csv
from tests.test_score_rule_schema import _csv_bytes, _valid_row


def _current():  # type: ignore[no-untyped-def]
    parsed = parse_score_rule_csv(_csv_bytes([_valid_row()]))
    assert parsed.issues == ()
    return parsed.rows[0]


def test_preview_classifies_unchanged_changed_new_and_version_conflict() -> None:
    current = _current()
    changed = replace(
        current,
        rule_version="synthetic-v2",
        definition=replace(current.definition, maximum_score=Decimal("900")),
        change_reason="합성 배점 변경",
    )
    new = replace(
        current,
        identity=replace(current.identity, admission_track_code="NEW_TRACK"),
        rule_version="synthetic-v1",
    )
    conflict = replace(changed, rule_version=current.rule_version)

    assert (
        build_score_rule_csv_preview(write_score_rule_csv((current,)), (current,))
        .items[0]
        .classification
        == "UNCHANGED"
    )
    changed_preview = build_score_rule_csv_preview(write_score_rule_csv((changed,)), (current,))
    assert changed_preview.items[0].classification == "CHANGED"
    assert any(change.path == "maximum_score" for change in changed_preview.items[0].changes)
    assert (
        build_score_rule_csv_preview(write_score_rule_csv((new,)), (current,))
        .items[0]
        .classification
        == "NEW"
    )
    assert (
        build_score_rule_csv_preview(write_score_rule_csv((conflict,)), (current,))
        .items[0]
        .classification
        == "CONFLICT"
    )


def test_errors_are_reported_and_never_become_drafts_implicitly() -> None:
    current = _current()
    invalid = _valid_row()
    invalid["administrator_note"] = "=EXECUTABLE"
    preview = build_score_rule_csv_preview(_csv_bytes([invalid]), (current,))

    assert preview.issues
    assert preview.items == ()
    with pytest.raises(DraftSelectionError):
        prepare_selected_score_rule_drafts(preview, ())


def test_admin_can_confirm_only_selected_valid_new_or_changed_rows_as_drafts() -> None:
    current = _current()
    changed = replace(
        current,
        rule_version="synthetic-v2",
        definition=replace(current.definition, maximum_score=Decimal("900")),
        change_reason="합성 배점 변경",
    )
    preview = build_score_rule_csv_preview(write_score_rule_csv((changed,)), (current,))

    drafts = prepare_selected_score_rule_drafts(preview, (changed.identity.key,))

    assert len(drafts) == 1
    assert drafts[0].lifecycle_status == "DRAFT"
    assert drafts[0].rule == changed
    assert drafts[0].supersedes_rule_version == current.rule_version
    assert drafts[0].auto_publish is False
