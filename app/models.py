from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def new_id() -> str:
    return str(uuid4())


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Institution(TimestampMixin, Base):
    __tablename__ = "institutions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    institution_type: Mapped[str] = mapped_column(String(40), nullable=False)


class Campus(TimestampMixin, Base):
    __tablename__ = "campuses"
    __table_args__ = (UniqueConstraint("institution_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    institution_id: Mapped[str] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class Program(TimestampMixin, Base):
    __tablename__ = "programs"
    __table_args__ = (UniqueConstraint("campus_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    campus_id: Mapped[str] = mapped_column(
        ForeignKey("campuses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class AdmissionRound(TimestampMixin, Base):
    __tablename__ = "admission_rounds"
    __table_args__ = (UniqueConstraint("institution_id", "academic_year", "code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    institution_id: Mapped[str] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    academic_year: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class AdmissionTrack(TimestampMixin, Base):
    __tablename__ = "admission_tracks"
    __table_args__ = (UniqueConstraint("admission_round_id", "program_id", "code"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    admission_round_id: Mapped[str] = mapped_column(
        ForeignKey("admission_rounds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    program_id: Mapped[str] = mapped_column(
        ForeignKey("programs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class SourceDocument(TimestampMixin, Base):
    __tablename__ = "source_documents"
    __table_args__ = (
        CheckConstraint("academic_year >= 2000", name="academic_year_valid"),
        CheckConstraint("page_count > 0", name="page_count_positive"),
        CheckConstraint(
            "document_status IN ('DRAFT', 'EXTRACTED', 'VERIFIED', "
            "'HUMAN_APPROVED', 'PUBLISHED', 'SUPERSEDED')",
            name="document_status_valid",
        ),
        CheckConstraint(
            "year_consistency_status IN ('CONSISTENT', 'MIXED_YEAR', 'UNKNOWN')",
            name="year_consistency_status_valid",
        ),
        CheckConstraint(
            "document_status != 'PUBLISHED' OR "
            "(year_consistency_status = 'CONSISTENT' AND verification_status = 'HUMAN_APPROVED')",
            name="published_document_is_verified",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    academic_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    institution_id: Mapped[str | None] = mapped_column(
        ForeignKey("institutions.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    campus_id: Mapped[str | None] = mapped_column(
        ForeignKey("campuses.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    document_type: Mapped[str] = mapped_column(String(60), nullable=False)
    document_status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision_label: Mapped[str | None] = mapped_column(String(120))
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_documents.id", ondelete="RESTRICT"), nullable=True
    )
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_years: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    year_consistency_status: Mapped[str] = mapped_column(String(30), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")


class SourceDocumentPage(TimestampMixin, Base):
    __tablename__ = "source_document_pages"
    __table_args__ = (
        UniqueConstraint("source_document_id", "page_number"),
        CheckConstraint("page_number > 0", name="page_number_positive"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_document_id: Mapped[str] = mapped_column(
        ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_academic_year: Mapped[int | None] = mapped_column(Integer)
    verification_status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")


class SourceCitation(TimestampMixin, Base):
    __tablename__ = "source_citations"
    __table_args__ = (CheckConstraint("page_number > 0", name="page_number_positive"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_document_id: Mapped[str] = mapped_column(
        ForeignKey("source_documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_document_page_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_document_pages.id", ondelete="RESTRICT"), nullable=True
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    locator: Mapped[str | None] = mapped_column(String(240))
    excerpt_digest: Mapped[str | None] = mapped_column(String(64))


class RuleReview(TimestampMixin, Base):
    __tablename__ = "rule_reviews"
    __table_args__ = (UniqueConstraint("rule_type", "rule_id", "review_kind", "reviewer_ref"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rule_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    review_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reviewer_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class RuleRecordMixin(TimestampMixin):
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    admission_track_id: Mapped[str | None] = mapped_column(
        ForeignKey("admission_tracks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    version: Mapped[str] = mapped_column(String(120), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")
    rule_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    source_citation_id: Mapped[str | None] = mapped_column(
        ForeignKey("source_citations.id", ondelete="RESTRICT"), nullable=True
    )
    independent_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    golden_test_ref: Mapped[str | None] = mapped_column(String(240))
    human_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def rule_constraints() -> tuple[CheckConstraint, CheckConstraint, UniqueConstraint]:
    return (
        CheckConstraint(
            "lifecycle_status IN ('DRAFT', 'EXTRACTED', 'VERIFIED', 'TESTED', "
            "'HUMAN_APPROVED', 'PUBLISHED', 'SUPERSEDED')",
            name="lifecycle_status_valid",
        ),
        CheckConstraint(
            "lifecycle_status != 'PUBLISHED' OR "
            "(source_citation_id IS NOT NULL AND independent_verified "
            "AND golden_test_ref IS NOT NULL AND human_approved_at IS NOT NULL)",
            name="published_rule_has_evidence",
        ),
        UniqueConstraint("admission_track_id", "version"),
    )


class AdmissionEligibilityRule(RuleRecordMixin, Base):
    __tablename__ = "admission_eligibility_rules"
    __table_args__ = rule_constraints()


class GradeSourceScopeRule(RuleRecordMixin, Base):
    __tablename__ = "grade_source_scope_rules"
    __table_args__ = rule_constraints()


class ScoreRule(RuleRecordMixin, Base):
    __tablename__ = "score_rules"
    __table_args__ = rule_constraints()


class MultipleApplicationRule(RuleRecordMixin, Base):
    __tablename__ = "multiple_application_rules"
    __table_args__ = rule_constraints()


class DisqualificationRule(RuleRecordMixin, Base):
    __tablename__ = "disqualification_rules"
    __table_args__ = rule_constraints()


class ScoreAdjustmentRule(RuleRecordMixin, Base):
    __tablename__ = "score_adjustment_rules"
    __table_args__ = rule_constraints()


class DocumentRequirement(RuleRecordMixin, Base):
    __tablename__ = "document_requirements"
    __table_args__ = rule_constraints()


class TieBreakRule(RuleRecordMixin, Base):
    __tablename__ = "tie_break_rules"
    __table_args__ = rule_constraints()


class ImportBatch(TimestampMixin, Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint("char_length(source_hash) = 64", name="source_hash_length"),
        CheckConstraint(
            "source_format IN ('csv', 'pasted_table', 'xlsx', 'text_pdf', "
            "'image_png', 'image_jpeg', 'clipboard_image', 'scanned_pdf')",
            name="source_format_valid",
        ),
        CheckConstraint("confirmed_row_count > 0", name="confirmed_row_count_positive"),
        CheckConstraint(
            "status IN ('PENDING_PURGE', 'CONFIRMED')",
            name="status_valid",
        ),
        CheckConstraint(
            "status != 'CONFIRMED' OR original_purged_at IS NOT NULL",
            name="confirmed_source_is_purged",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_format: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING_PURGE")
    confirmed_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    original_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StudentAcademicRecord(TimestampMixin, Base):
    __tablename__ = "student_academic_records"
    __table_args__ = (
        UniqueConstraint("student_id", "academic_year", "grade", "semester", "record_source"),
        CheckConstraint("grade BETWEEN 1 AND 3", name="grade_valid"),
        CheckConstraint("semester BETWEEN 1 AND 2", name="semester_valid"),
        CheckConstraint(
            "record_source IN ('HOME_SCHOOL_RECORD', 'VOCATIONAL_TRAINING_RECORD', "
            "'GED_RECORD', 'MANUAL_INPUT')",
            name="record_source_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    student_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    academic_year: Mapped[int] = mapped_column(Integer, nullable=False)
    grade: Mapped[int] = mapped_column(Integer, nullable=False)
    semester: Mapped[int] = mapped_column(Integer, nullable=False)
    record_source: Mapped[str] = mapped_column(String(40), nullable=False)
    original_school_id: Mapped[str | None] = mapped_column(String(120))
    vocational_institution_name: Mapped[str | None] = mapped_column(String(200))
    is_vocational_training_semester: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    verification_status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")


class StudentCourseRecord(TimestampMixin, Base):
    __tablename__ = "student_course_records"
    __table_args__ = (
        CheckConstraint(
            "raw_score_label IS NULL OR raw_score_label = 'P'",
            name="raw_score_label_valid",
        ),
        CheckConstraint(
            "raw_score IS NULL OR raw_score_label IS NULL",
            name="raw_score_value_or_label",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    import_batch_id: Mapped[str | None] = mapped_column(
        ForeignKey("import_batches.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    academic_record_id: Mapped[str] = mapped_column(
        ForeignKey("student_academic_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subject_group: Mapped[str | None] = mapped_column(String(120))
    subject_name: Mapped[str] = mapped_column(String(200), nullable=False)
    credits: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    raw_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    raw_score_label: Mapped[str | None] = mapped_column(String(20))
    course_mean: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    standard_deviation: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    achievement_level: Mapped[str | None] = mapped_column(String(20))
    enrollment_count: Mapped[int | None] = mapped_column(Integer)
    rank_grade: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    achievement_distribution: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source_page: Mapped[int | None] = mapped_column(Integer)
    extraction_method: Mapped[str] = mapped_column(String(40), nullable=False)
    extraction_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    user_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class VocationalCourseReport(TimestampMixin, Base):
    __tablename__ = "vocational_course_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    academic_record_id: Mapped[str] = mapped_column(
        ForeignKey("student_academic_records.id", ondelete="CASCADE"), nullable=False, index=True
    )
    course_name: Mapped[str] = mapped_column(String(200), nullable=False)
    report_type: Mapped[str] = mapped_column(String(40), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(30), nullable=False, default="PENDING")


class AssessmentComponent(TimestampMixin, Base):
    __tablename__ = "assessment_components"
    __table_args__ = (UniqueConstraint("vocational_course_report_id", "name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vocational_course_report_id: Mapped[str] = mapped_column(
        ForeignKey("vocational_course_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    weight: Mapped[Decimal | None] = mapped_column(Numeric(7, 4))
    maximum_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))


class VocationalStudentResult(TimestampMixin, Base):
    __tablename__ = "vocational_student_results"
    __table_args__ = (UniqueConstraint("vocational_course_report_id", "student_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vocational_course_report_id: Mapped[str] = mapped_column(
        ForeignKey("vocational_course_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    student_id: Mapped[str] = mapped_column(String(120), nullable=False)
    final_score: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    achievement_level: Mapped[str | None] = mapped_column(String(20))


class VocationalCourseStatistic(TimestampMixin, Base):
    __tablename__ = "vocational_course_statistics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    vocational_course_report_id: Mapped[str] = mapped_column(
        ForeignKey("vocational_course_reports.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    course_mean: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    standard_deviation: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    enrollment_count: Mapped[int | None] = mapped_column(Integer)


__all__ = [
    "AdmissionEligibilityRule",
    "AdmissionRound",
    "AdmissionTrack",
    "AssessmentComponent",
    "Campus",
    "DisqualificationRule",
    "DocumentRequirement",
    "GradeSourceScopeRule",
    "ImportBatch",
    "Institution",
    "MultipleApplicationRule",
    "Program",
    "RuleReview",
    "ScoreAdjustmentRule",
    "ScoreRule",
    "SourceCitation",
    "SourceDocument",
    "SourceDocumentPage",
    "StudentAcademicRecord",
    "StudentCourseRecord",
    "TieBreakRule",
    "VocationalCourseReport",
    "VocationalCourseStatistic",
    "VocationalStudentResult",
]
