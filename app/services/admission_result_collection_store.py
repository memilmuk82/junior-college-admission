from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models import AdmissionResultRawBatch, AdmissionResultRawPage
from app.services.admission_results import RawAdmissionResultCollection


def persist_raw_collection(
    session: Session, collection: RawAdmissionResultCollection
) -> AdmissionResultRawBatch:
    batch = AdmissionResultRawBatch(
        source_code=collection.source_code,
        expected_academic_year=collection.expected_academic_year,
        collection_digest=collection.collection_digest,
        page_count=collection.page_count,
        row_count=collection.row_count,
        policy_payload={
            "timeout_seconds": collection.policy.timeout_seconds,
            "max_retries": collection.policy.max_retries,
            "retry_delay_seconds": collection.policy.retry_delay_seconds,
            "rate_limit_seconds": collection.policy.rate_limit_seconds,
            "max_response_bytes": collection.policy.max_response_bytes,
            "max_pages": collection.policy.max_pages,
            "max_rows": collection.policy.max_rows,
        },
        status="COLLECTED",
        collected_at=datetime.now(UTC),
    )
    session.add(batch)
    session.flush()
    for page in collection.pages:
        session.add(
            AdmissionResultRawPage(
                raw_batch_id=batch.id,
                page_number=page.page_number,
                request_fingerprint=page.request_fingerprint,
                response_digest=page.response_digest,
                row_count=len(page.rows),
                raw_rows=[row.as_dict() for row in page.rows],
            )
        )
    return batch


__all__ = ["persist_raw_collection"]
