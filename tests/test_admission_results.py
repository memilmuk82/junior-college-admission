from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast

import pytest

from app.services.admission_results import (
    AdmissionResultCandidate,
    AdmissionResultCollectionError,
    AdmissionResultKey,
    Approval,
    CollectionPolicy,
    HistoricalRuleReference,
    QualityBaseline,
    SourceRequest,
    SourceResponse,
    SourceTransportError,
    StagingBlockedError,
    collect_admission_result_raw,
    publish_staging_batch,
    stage_admission_result_raw,
)


@dataclass
class SyntheticAdapter:
    policy: CollectionPolicy = CollectionPolicy(
        timeout_seconds=5,
        max_retries=1,
        retry_delay_seconds=1,
        rate_limit_seconds=2,
    )
    source_code: str = "SYNTHETIC_RESULTS"

    def build_requests(self, academic_year: int) -> tuple[SourceRequest, ...]:
        return (
            SourceRequest(self.source_code, "/synthetic/results", academic_year, 1),
            SourceRequest(self.source_code, "/synthetic/results", academic_year, 2),
        )

    def extract_rows(
        self, request: SourceRequest, response: SourceResponse
    ) -> tuple[dict[str, object], ...]:
        assert response.content_type == "application/json"
        decoded = json.loads(response.body)
        assert isinstance(decoded, list)
        return tuple(dict(row) for row in decoded)

    def normalize(self, raw: dict[str, object]) -> AdmissionResultCandidate:
        return AdmissionResultCandidate(
            key=AdmissionResultKey(
                academic_year=int(cast(str | int, raw["academic_year"])),
                university_code=str(raw["university_code"]),
                campus_code=str(raw["campus_code"]),
                admission_round=str(raw["admission_round"]),
                admission_track_code=str(raw["admission_track_code"]),
                program_code=str(raw["program_code"]),
            ),
            applicant_count=int(cast(str | int, raw["applicant_count"])),
            admitted_count=int(cast(str | int, raw["admitted_count"])),
            competition_rate=Decimal(str(raw["competition_rate"])),
            highest_score=Decimal(str(raw["highest_score"])),
            average_score=Decimal(str(raw["average_score"])),
            lowest_score=Decimal(str(raw["lowest_score"])),
            score_basis=str(raw["score_basis"]),
        )


class SyntheticTransport:
    def __init__(self, responses: dict[int, list[SourceResponse | Exception]]) -> None:
        self.responses = responses
        self.calls: list[tuple[int, int]] = []

    def fetch(self, request: SourceRequest, *, timeout_seconds: int) -> SourceResponse:
        self.calls.append((request.page_number, timeout_seconds))
        outcome = self.responses[request.page_number].pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _response(*rows: dict[str, object]) -> SourceResponse:
    return SourceResponse(
        status_code=200,
        content_type="application/json",
        body=json.dumps(rows, ensure_ascii=False).encode(),
    )


def _row(
    program_code: str,
    *,
    academic_year: int = 2026,
    university_code: str = "SYNTHETIC_U",
) -> dict[str, object]:
    return {
        "academic_year": academic_year,
        "university_code": university_code,
        "campus_code": "MAIN",
        "admission_round": "EARLY_1",
        "admission_track_code": "GENERAL",
        "program_code": program_code,
        "applicant_count": 20,
        "admitted_count": 10,
        "competition_rate": "2.0",
        "highest_score": "3.00",
        "average_score": "4.50",
        "lowest_score": "6.00",
        "score_basis": "RANK_GRADE",
    }


def _collect(*rows: dict[str, object]):  # type: ignore[no-untyped-def]
    first = rows[:1]
    second = rows[1:]
    transport = SyntheticTransport({1: [_response(*first)], 2: [_response(*second)]})
    return collect_admission_result_raw(
        SyntheticAdapter(), transport, academic_year=2026, wait=lambda _seconds: None
    )


def test_collection_separates_requests_responses_and_retries_with_policy() -> None:
    waits: list[int] = []
    transport = SyntheticTransport(
        {
            1: [SourceTransportError("temporary"), _response(_row("P1"))],
            2: [_response(_row("P2"))],
        }
    )

    raw = collect_admission_result_raw(
        SyntheticAdapter(), transport, academic_year=2026, wait=waits.append
    )

    assert transport.calls == [(1, 5), (1, 5), (2, 5)]
    assert waits == [1, 2]
    assert raw.page_count == 2
    assert raw.row_count == 2
    assert len(raw.collection_digest) == 64
    assert all(len(page.request_fingerprint) == 64 for page in raw.pages)
    assert all(len(page.response_digest) == 64 for page in raw.pages)


def test_collection_stops_after_bounded_retries() -> None:
    transport = SyntheticTransport(
        {
            1: [SourceTransportError("first"), SourceTransportError("second")],
            2: [_response()],
        }
    )

    with pytest.raises(AdmissionResultCollectionError):
        collect_admission_result_raw(
            SyntheticAdapter(), transport, academic_year=2026, wait=lambda _seconds: None
        )

    assert transport.calls == [(1, 5), (1, 5)]


def test_valid_staging_requires_whole_batch_human_approval_and_pins_rule_version() -> None:
    raw = _collect(_row("P1"), _row("P2"))
    staged = stage_admission_result_raw(raw, SyntheticAdapter())

    assert staged.status == "READY"
    assert staged.valid_row_count == 2
    published = publish_staging_batch(
        staged,
        Approval(
            approved_by="synthetic-admin",
            approved_at=datetime(2026, 7, 13, 1, 0, tzinfo=UTC),
            confirmed_row_count=2,
        ),
        HistoricalRuleReference("score-rule-2026", "official-v1", 2026),
    )

    assert len(published.rows) == 2
    assert published.approved_by == "synthetic-admin"
    assert {row.rule_reference.version for row in published.rows if row.rule_reference} == {
        "official-v1"
    }


@pytest.mark.parametrize(
    ("rows", "expected_code"),
    [
        ((_row("P1", academic_year=2027), _row("P2")), "MIXED_ACADEMIC_YEAR"),
        ((_row("P1"), _row("P1")), "DUPLICATE_BUSINESS_KEY"),
        ((_row("P1", university_code=""), _row("P2")), "REQUIRED_KEY_MISSING"),
    ],
)
def test_invalid_rows_block_the_entire_batch(
    rows: tuple[dict[str, object], ...], expected_code: str
) -> None:
    staged = stage_admission_result_raw(_collect(*rows), SyntheticAdapter())

    assert staged.status == "BLOCKED"
    assert any(issue.code == expected_code for issue in staged.issues) or any(
        issue.code == expected_code for row in staged.rows for issue in row.issues
    )
    with pytest.raises(StagingBlockedError):
        publish_staging_batch(
            staged,
            Approval("synthetic-admin", datetime(2026, 7, 13, tzinfo=UTC), 1),
        )


@pytest.mark.parametrize(
    "baseline",
    [
        QualityBaseline(previous_row_count=10, previous_page_count=2, minimum_ratio=Decimal("0.8")),
        QualityBaseline(previous_row_count=2, previous_page_count=4, minimum_ratio=Decimal("0.8")),
    ],
)
def test_row_or_page_count_drop_blocks_staging(baseline: QualityBaseline) -> None:
    staged = stage_admission_result_raw(
        _collect(_row("P1"), _row("P2")), SyntheticAdapter(), baseline=baseline
    )

    assert staged.status == "BLOCKED"
    assert any(issue.code in {"ROW_COUNT_DROP", "PAGE_COUNT_DROP"} for issue in staged.issues)


def test_raw_cannot_be_published_and_rule_year_must_match_result_year() -> None:
    raw = _collect(_row("P1"), _row("P2"))
    with pytest.raises(TypeError):
        publish_staging_batch(
            raw,
            Approval("synthetic-admin", datetime(2026, 7, 13, tzinfo=UTC), 2),
        )

    staged = stage_admission_result_raw(raw, SyntheticAdapter())
    with pytest.raises(StagingBlockedError):
        publish_staging_batch(
            staged,
            Approval("synthetic-admin", datetime(2026, 7, 13, tzinfo=UTC), 2),
            HistoricalRuleReference("current-rule", "2027-v1", 2027),
        )
