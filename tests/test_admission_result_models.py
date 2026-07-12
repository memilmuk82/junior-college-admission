from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AdmissionResultPublished,
    AdmissionResultPublishedBatch,
    AdmissionResultRawBatch,
    AdmissionResultRawPage,
    AdmissionResultStagingBatch,
    AdmissionResultStagingRow,
    ScoreRule,
)
from app.services.admission_result_analysis import load_published_admission_result_for_analysis
from app.services.admission_results import AdmissionResultKey


@pytest.fixture
def session(postgres_engine: Engine) -> Iterator[Session]:
    connection = postgres_engine.connect()
    transaction = connection.begin()
    database_session = Session(bind=connection)
    try:
        yield database_session
    finally:
        database_session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def _raw(session: Session, suffix: str = "a") -> AdmissionResultRawBatch:
    batch = AdmissionResultRawBatch(
        source_code="SYNTHETIC_RESULTS",
        expected_academic_year=2026,
        collection_digest=suffix * 64,
        page_count=1,
        row_count=1,
        policy_payload={"timeout_seconds": 5, "max_retries": 1},
        status="COLLECTED",
        collected_at=datetime(2026, 7, 13, tzinfo=UTC),
    )
    session.add(batch)
    session.flush()
    session.add(
        AdmissionResultRawPage(
            raw_batch_id=batch.id,
            page_number=1,
            request_fingerprint="b" * 64,
            response_digest="c" * 64,
            row_count=1,
            raw_rows=[{"synthetic": "row"}],
        )
    )
    session.flush()
    return batch


def _staging(
    session: Session, raw: AdmissionResultRawBatch
) -> tuple[AdmissionResultStagingBatch, AdmissionResultStagingRow]:
    batch = AdmissionResultStagingBatch(
        raw_batch_id=raw.id,
        expected_academic_year=2026,
        status="READY",
        total_row_count=1,
        valid_row_count=1,
        error_row_count=0,
        validation_issues=[],
    )
    session.add(batch)
    session.flush()
    row = AdmissionResultStagingRow(
        staging_batch_id=batch.id,
        source_row_number=1,
        academic_year=2026,
        university_code="SYNTHETIC_U",
        campus_code="MAIN",
        admission_round="EARLY_1",
        admission_track_code="GENERAL",
        program_code="P1",
        applicant_count=0,
        admitted_count=0,
        competition_rate=Decimal("0"),
        highest_score=Decimal("0"),
        average_score=None,
        lowest_score=None,
        score_basis="RANK_GRADE",
        validation_status="VALID",
        validation_issues=[],
    )
    session.add(row)
    session.flush()
    return batch, row


def test_raw_staging_and_human_approved_published_rows_remain_separate(session: Session) -> None:
    raw = _raw(session)
    staging, staging_row = _staging(session, raw)
    published_batch = AdmissionResultPublishedBatch(
        staging_batch_id=staging.id,
        approved_by="synthetic-admin",
        approved_at=datetime(2026, 7, 13, 1, 0, tzinfo=UTC),
        confirmed_row_count=1,
    )
    session.add(published_batch)
    session.flush()
    published = AdmissionResultPublished(
        published_batch_id=published_batch.id,
        staging_row_id=staging_row.id,
        academic_year=2026,
        university_code="SYNTHETIC_U",
        campus_code="MAIN",
        admission_round="EARLY_1",
        admission_track_code="GENERAL",
        program_code="P1",
        publication_version="synthetic-v1",
        lifecycle_status="PUBLISHED",
        applicant_count=0,
        admitted_count=0,
        competition_rate=Decimal("0"),
        highest_score=Decimal("0"),
        score_basis="RANK_GRADE",
    )
    session.add(published)
    session.flush()

    assert raw.id != staging.id != published_batch.id != published.id
    assert published.applicant_count == 0
    assert published.competition_rate == Decimal("0")
    analysis_input = load_published_admission_result_for_analysis(
        session,
        AdmissionResultKey(2026, "SYNTHETIC_U", "MAIN", "EARLY_1", "GENERAL", "P1"),
    )
    assert analysis_input.publication_version == "synthetic-v1"
    assert analysis_input.applicant_count == 0
    assert analysis_input.historical_rule is None


def test_ready_staging_batch_cannot_contain_error_rows(session: Session) -> None:
    raw = _raw(session)
    session.add(
        AdmissionResultStagingBatch(
            raw_batch_id=raw.id,
            expected_academic_year=2026,
            status="READY",
            total_row_count=1,
            valid_row_count=0,
            error_row_count=1,
            validation_issues=[{"code": "SYNTHETIC_ERROR"}],
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()


def test_published_result_rejects_rule_version_from_another_year(session: Session) -> None:
    raw = _raw(session)
    staging, staging_row = _staging(session, raw)
    rule = ScoreRule(
        version="2027-v1",
        lifecycle_status="DRAFT",
        rule_payload={"schema_version": 1},
    )
    published_batch = AdmissionResultPublishedBatch(
        staging_batch_id=staging.id,
        approved_by="synthetic-admin",
        approved_at=datetime(2026, 7, 13, 1, 0, tzinfo=UTC),
        confirmed_row_count=1,
    )
    session.add_all([rule, published_batch])
    session.flush()
    session.add(
        AdmissionResultPublished(
            published_batch_id=published_batch.id,
            staging_row_id=staging_row.id,
            academic_year=2026,
            university_code="SYNTHETIC_U",
            campus_code="MAIN",
            admission_round="EARLY_1",
            admission_track_code="GENERAL",
            program_code="P1",
            publication_version="synthetic-v1",
            lifecycle_status="PUBLISHED",
            applicant_count=10,
            score_rule_id=rule.id,
            score_rule_version=rule.version,
            score_rule_academic_year=2027,
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()
