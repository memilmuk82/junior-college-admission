from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models import ImportBatch, StudentAcademicRecord, StudentCourseRecord
from app.services.confirmed_imports import confirm_structured_import
from app.services.structured_imports import StructuredImportPreview, parse_structured_text
from app.services.temporary_uploads import (
    DeletionVerificationError,
    TemporaryUploadStore,
)
from app.services.text_pdf_imports import parse_academic_record_page_texts


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


def _preview() -> StructuredImportPreview:
    source = "\n".join(
        [
            "학년도,학년,학기,과목,원점수",
            "2026,3,1,합성 확인 과목,91",
            "2026,3,1,합성 미확인 과목,77",
        ]
    )
    return parse_structured_text(source, source_format="csv")


def _temporary_session(tmp_path: Path) -> tuple[TemporaryUploadStore, str]:
    store = TemporaryUploadStore(tmp_path)
    review_session_id = store.create_session()
    store.write_artifact(
        review_session_id,
        b"synthetic-source",
        kind="original",
        suffix=".csv",
    )
    store.write_artifact(
        review_session_id,
        b"synthetic-derived",
        kind="derived",
        suffix=".txt",
    )
    return store, review_session_id


def test_only_confirmed_rows_are_stored_and_temporary_files_are_purged(
    session: Session, tmp_path: Path
) -> None:
    store, review_session_id = _temporary_session(tmp_path)

    result = confirm_structured_import(
        session,
        preview=_preview(),
        confirmed_row_indices=(0,),
        student_id="synthetic-confirmed-student",
        record_source="HOME_SCHOOL_RECORD",
        upload_store=store,
        review_session_id=review_session_id,
    )

    stored_courses = session.scalars(
        select(StudentCourseRecord).where(
            StudentCourseRecord.import_batch_id == result.import_batch_id
        )
    ).all()
    batch = session.get(ImportBatch, result.import_batch_id)

    assert [course.subject_name for course in stored_courses] == ["합성 확인 과목"]
    assert all(course.user_verified for course in stored_courses)
    assert batch is not None
    assert batch.confirmed_row_count == 1
    assert batch.original_purged_at is not None
    assert not store.session_path(review_session_id).exists()


def test_pass_value_is_preserved_as_label_instead_of_becoming_zero(
    session: Session, tmp_path: Path
) -> None:
    preview = parse_structured_text(
        "학년도,학년,학기,과목,원점수\n2026,3,1,합성 이수 과목,P",
        source_format="csv",
    )
    store, review_session_id = _temporary_session(tmp_path)

    result = confirm_structured_import(
        session,
        preview=preview,
        confirmed_row_indices=(0,),
        student_id="synthetic-pass-student",
        record_source="HOME_SCHOOL_RECORD",
        upload_store=store,
        review_session_id=review_session_id,
    )

    course = session.scalar(
        select(StudentCourseRecord).where(
            StudentCourseRecord.import_batch_id == result.import_batch_id
        )
    )
    assert course is not None
    assert course.raw_score is None
    assert course.raw_score_label == "P"


def test_deletion_failure_rolls_back_confirmed_database_rows(
    session: Session, tmp_path: Path
) -> None:
    store, review_session_id = _temporary_session(tmp_path)

    with patch.object(
        store,
        "purge_session",
        side_effect=DeletionVerificationError("synthetic deletion failure"),
    ):
        with pytest.raises(DeletionVerificationError):
            confirm_structured_import(
                session,
                preview=_preview(),
                confirmed_row_indices=(0,),
                student_id="synthetic-rollback-student",
                record_source="HOME_SCHOOL_RECORD",
                upload_store=store,
                review_session_id=review_session_id,
            )

    assert (
        session.scalar(
            select(StudentAcademicRecord).where(
                StudentAcademicRecord.student_id == "synthetic-rollback-student"
            )
        )
        is None
    )
    assert (
        session.scalar(select(ImportBatch).where(ImportBatch.source_hash == _preview().source_hash))
        is None
    )


def test_confirmed_text_pdf_row_keeps_page_trace(session: Session, tmp_path: Path) -> None:
    preview = parse_academic_record_page_texts(
        (
            "합성 표지",
            "교과학습발달상황\n학년도|학년|학기|과목|원점수\n2026|3|1|합성 PDF 과목|91",
        ),
        source_hash="c" * 64,
    )
    store, review_session_id = _temporary_session(tmp_path)

    result = confirm_structured_import(
        session,
        preview=preview,
        confirmed_row_indices=(0,),
        student_id="synthetic-pdf-student",
        record_source="HOME_SCHOOL_RECORD",
        upload_store=store,
        review_session_id=review_session_id,
    )

    course = session.scalar(
        select(StudentCourseRecord).where(
            StudentCourseRecord.import_batch_id == result.import_batch_id
        )
    )
    batch = session.get(ImportBatch, result.import_batch_id)
    assert course is not None
    assert batch is not None
    assert course.extraction_method == "TEXT_PDF"
    assert course.source_page == 2
    assert batch.source_format == "text_pdf"
