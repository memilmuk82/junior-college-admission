from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ImportBatch, StudentAcademicRecord, StudentCourseRecord
from app.services.structured_imports import NormalizedCourseRow, StructuredImportPreview
from app.services.temporary_uploads import TemporaryUploadStore

RECORD_SOURCES = frozenset(
    {
        "HOME_SCHOOL_RECORD",
        "VOCATIONAL_TRAINING_RECORD",
        "GED_RECORD",
        "MANUAL_INPUT",
    }
)
EXTRACTION_METHODS = {
    "csv": "STRUCTURED_CSV",
    "pasted_table": "PASTED_TABLE",
    "xlsx": "STRUCTURED_XLSX",
    "text_pdf": "TEXT_PDF",
}


class ConfirmationValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ConfirmedImportResult:
    import_batch_id: str
    academic_record_ids: tuple[str, ...]
    course_record_ids: tuple[str, ...]


def _confirmed_rows(
    preview: StructuredImportPreview, confirmed_row_indices: tuple[int, ...]
) -> tuple[NormalizedCourseRow, ...]:
    if not confirmed_row_indices:
        raise ConfirmationValidationError("확인된 행을 한 개 이상 선택해야 합니다.")
    if len(set(confirmed_row_indices)) != len(confirmed_row_indices):
        raise ConfirmationValidationError("같은 행을 중복 선택할 수 없습니다.")

    rows: list[NormalizedCourseRow] = []
    for index in confirmed_row_indices:
        if index < 0 or index >= len(preview.rows):
            raise ConfirmationValidationError("확인 행 인덱스가 범위를 벗어났습니다.")
        row = preview.rows[index]
        if (
            row.academic_year is None
            or row.grade is None
            or row.semester is None
            or row.subject_name is None
        ):
            raise ConfirmationValidationError(
                "확인 행에는 학년도·학년·학기·과목이 모두 필요합니다."
            )
        rows.append(row)
    return tuple(rows)


def _academic_record(
    session: Session,
    *,
    student_id: str,
    record_source: str,
    row: NormalizedCourseRow,
) -> StudentAcademicRecord:
    assert row.academic_year is not None
    assert row.grade is not None
    assert row.semester is not None
    existing = session.scalar(
        select(StudentAcademicRecord).where(
            StudentAcademicRecord.student_id == student_id,
            StudentAcademicRecord.academic_year == row.academic_year,
            StudentAcademicRecord.grade == row.grade,
            StudentAcademicRecord.semester == row.semester,
            StudentAcademicRecord.record_source == record_source,
        )
    )
    if existing is not None:
        return existing

    record = StudentAcademicRecord(
        student_id=student_id,
        academic_year=row.academic_year,
        grade=row.grade,
        semester=row.semester,
        record_source=record_source,
        is_vocational_training_semester=record_source == "VOCATIONAL_TRAINING_RECORD",
        verification_status="USER_VERIFIED",
    )
    session.add(record)
    session.flush()
    return record


def confirm_structured_import(
    session: Session,
    *,
    preview: StructuredImportPreview,
    confirmed_row_indices: tuple[int, ...],
    student_id: str,
    record_source: str,
    upload_store: TemporaryUploadStore,
    review_session_id: str,
) -> ConfirmedImportResult:
    normalized_student_id = student_id.strip()
    if not normalized_student_id:
        raise ConfirmationValidationError("내부 학생 식별자가 필요합니다.")
    if record_source not in RECORD_SOURCES:
        raise ConfirmationValidationError("지원하지 않는 성적 출처입니다.")
    rows = _confirmed_rows(preview, confirmed_row_indices)

    batch = ImportBatch(
        source_hash=preview.source_hash,
        source_format=preview.source_format,
        status="PENDING_PURGE",
        confirmed_row_count=len(rows),
    )
    session.add(batch)
    academic_records: dict[tuple[int, int, int], StudentAcademicRecord] = {}
    course_records: list[StudentCourseRecord] = []

    try:
        session.flush()
        for row in rows:
            assert row.academic_year is not None
            assert row.grade is not None
            assert row.semester is not None
            assert row.subject_name is not None
            academic_key = (row.academic_year, row.grade, row.semester)
            academic_record = academic_records.get(academic_key)
            if academic_record is None:
                academic_record = _academic_record(
                    session,
                    student_id=normalized_student_id,
                    record_source=record_source,
                    row=row,
                )
                academic_records[academic_key] = academic_record

            raw_score = row.raw_score if isinstance(row.raw_score, Decimal) else None
            raw_score_label = row.raw_score if isinstance(row.raw_score, str) else None
            course_record = StudentCourseRecord(
                import_batch_id=batch.id,
                academic_record_id=academic_record.id,
                subject_group=row.subject_group,
                subject_name=row.subject_name,
                credits=row.credits,
                raw_score=raw_score,
                raw_score_label=raw_score_label,
                course_mean=row.course_mean,
                standard_deviation=row.standard_deviation,
                achievement_level=row.achievement_level,
                enrollment_count=row.enrollment_count,
                rank_grade=row.rank_grade,
                source_page=row.source_page,
                extraction_method=EXTRACTION_METHODS[preview.source_format],
                user_verified=True,
            )
            session.add(course_record)
            course_records.append(course_record)

        session.flush()
        upload_store.purge_session(review_session_id)
        batch.status = "CONFIRMED"
        batch.original_purged_at = datetime.now(UTC)
        session.commit()
    except Exception:
        session.rollback()
        raise

    return ConfirmedImportResult(
        import_batch_id=batch.id,
        academic_record_ids=tuple(record.id for record in academic_records.values()),
        course_record_ids=tuple(record.id for record in course_records),
    )
