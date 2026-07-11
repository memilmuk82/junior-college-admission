from decimal import Decimal
from pathlib import Path

from app.services.review_state import ReviewStateStore
from app.services.structured_imports import (
    NormalizationIssue,
    StructuredImportPreview,
    parse_structured_text,
)
from app.services.temporary_uploads import TemporaryUploadStore


def test_review_state_round_trip_preserves_only_normalized_preview(tmp_path: Path) -> None:
    upload_store = TemporaryUploadStore(tmp_path)
    review_session_id = upload_store.create_session()
    preview = parse_structured_text(
        "학년도,학년,학기,교과,과목,이수단위,원점수\n2026,3,1,보통교과,합성 과목,3,P",
        source_format="csv",
    )
    preview = StructuredImportPreview(
        source_hash=preview.source_hash,
        source_format=preview.source_format,
        rows=preview.rows,
        issues=(NormalizationIssue("OCR_REVIEW_REQUIRED", "ocr_text", 0),),
        ignored_headers=(),
    )
    state_store = ReviewStateStore(upload_store)

    state_store.save(
        review_session_id,
        preview,
        student_id="synthetic-review-student",
        record_source="HOME_SCHOOL_RECORD",
    )
    loaded = state_store.load(review_session_id)

    assert loaded.preview == preview
    assert loaded.preview.rows[0].credits == Decimal("3")
    assert loaded.preview.rows[0].raw_score == "P"
    assert loaded.student_id == "synthetic-review-student"
    assert list(upload_store.session_path(review_session_id).rglob("*review-state.json"))
