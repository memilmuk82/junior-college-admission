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
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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


class RuleVersionLineage(TimestampMixin, Base):
    __tablename__ = "rule_version_lineages"
    __table_args__ = (
        UniqueConstraint("rule_type", "rule_id"),
        CheckConstraint("rule_id != supersedes_rule_id", name="not_self_superseding"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rule_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    supersedes_rule_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)


class RuleAuditEvent(TimestampMixin, Base):
    __tablename__ = "rule_audit_events"
    __table_args__ = (
        CheckConstraint(
            "action IN ('DRAFT_CLONED', 'HUMAN_APPROVED', 'PUBLISHED', 'SUPERSEDED', 'REJECTED')",
            name="action_valid",
        ),
        CheckConstraint("char_length(actor_ref) > 0", name="actor_present"),
        CheckConstraint(
            "before_payload_digest IS NULL OR char_length(before_payload_digest) = 64",
            name="before_digest_valid",
        ),
        CheckConstraint(
            "after_payload_digest IS NULL OR char_length(after_payload_digest) = 64",
            name="after_digest_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rule_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    actor_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    before_payload_digest: Mapped[str | None] = mapped_column(String(64))
    after_payload_digest: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


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
    __table_args__ = (
        *rule_constraints(),
        Index(
            "uq_admission_eligibility_rules_one_published_per_track",
            "admission_track_id",
            unique=True,
            postgresql_where=text("lifecycle_status = 'PUBLISHED'"),
        ),
    )


class GradeSourceScopeRule(RuleRecordMixin, Base):
    __tablename__ = "grade_source_scope_rules"
    __table_args__ = (
        *rule_constraints(),
        Index(
            "uq_grade_source_scope_rules_one_published_per_track",
            "admission_track_id",
            unique=True,
            postgresql_where=text("lifecycle_status = 'PUBLISHED'"),
        ),
    )


class ScoreRule(RuleRecordMixin, Base):
    __tablename__ = "score_rules"
    __table_args__ = (
        *rule_constraints(),
        Index(
            "uq_score_rules_one_published_per_track",
            "admission_track_id",
            unique=True,
            postgresql_where=text("lifecycle_status = 'PUBLISHED'"),
        ),
    )


class MultipleApplicationRule(RuleRecordMixin, Base):
    __tablename__ = "multiple_application_rules"
    __table_args__ = (
        *rule_constraints(),
        Index(
            "uq_multiple_application_rules_one_published_per_track",
            "admission_track_id",
            unique=True,
            postgresql_where=text("lifecycle_status = 'PUBLISHED'"),
        ),
    )


class DisqualificationRule(RuleRecordMixin, Base):
    __tablename__ = "disqualification_rules"
    __table_args__ = (
        *rule_constraints(),
        Index(
            "uq_disqualification_rules_one_published_per_track",
            "admission_track_id",
            unique=True,
            postgresql_where=text("lifecycle_status = 'PUBLISHED'"),
        ),
    )


class ScoreAdjustmentRule(RuleRecordMixin, Base):
    __tablename__ = "score_adjustment_rules"
    __table_args__ = rule_constraints()


class DocumentRequirement(RuleRecordMixin, Base):
    __tablename__ = "document_requirements"
    __table_args__ = rule_constraints()


class TieBreakRule(RuleRecordMixin, Base):
    __tablename__ = "tie_break_rules"
    __table_args__ = rule_constraints()


class AdmissionResultRawBatch(TimestampMixin, Base):
    __tablename__ = "admission_result_raw_batches"
    __table_args__ = (
        CheckConstraint("expected_academic_year >= 2000", name="academic_year_valid"),
        CheckConstraint("char_length(collection_digest) = 64", name="digest_length"),
        CheckConstraint("page_count > 0", name="page_count_positive"),
        CheckConstraint("row_count > 0", name="row_count_positive"),
        CheckConstraint("status = 'COLLECTED'", name="status_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    source_code: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    expected_academic_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    collection_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    policy_payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="COLLECTED")
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AdmissionResultRawPage(TimestampMixin, Base):
    __tablename__ = "admission_result_raw_pages"
    __table_args__ = (
        UniqueConstraint("raw_batch_id", "page_number"),
        CheckConstraint("page_number > 0", name="page_number_positive"),
        CheckConstraint("row_count >= 0", name="row_count_nonnegative"),
        CheckConstraint("char_length(request_fingerprint) = 64", name="request_hash_length"),
        CheckConstraint("char_length(response_digest) = 64", name="response_hash_length"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    raw_batch_id: Mapped[str] = mapped_column(
        ForeignKey("admission_result_raw_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    response_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_rows: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)


class AdmissionResultStagingBatch(TimestampMixin, Base):
    __tablename__ = "admission_result_staging_batches"
    __table_args__ = (
        CheckConstraint("expected_academic_year >= 2000", name="academic_year_valid"),
        CheckConstraint("total_row_count > 0", name="total_row_count_positive"),
        CheckConstraint("valid_row_count >= 0", name="valid_row_count_nonnegative"),
        CheckConstraint("error_row_count >= 0", name="error_row_count_nonnegative"),
        CheckConstraint(
            "total_row_count = valid_row_count + error_row_count",
            name="row_counts_consistent",
        ),
        CheckConstraint("status IN ('READY', 'BLOCKED')", name="status_valid"),
        CheckConstraint(
            "status != 'READY' OR (error_row_count = 0 AND valid_row_count = total_row_count)",
            name="ready_batch_has_no_errors",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    raw_batch_id: Mapped[str] = mapped_column(
        ForeignKey("admission_result_raw_batches.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    expected_academic_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    total_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    error_row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    validation_issues: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )


class AdmissionResultStagingRow(TimestampMixin, Base):
    __tablename__ = "admission_result_staging_rows"
    __table_args__ = (
        UniqueConstraint(
            "staging_batch_id",
            "source_row_number",
            name="uq_admission_result_staging_rows_source_row",
        ),
        UniqueConstraint(
            "staging_batch_id",
            "academic_year",
            "university_code",
            "campus_code",
            "admission_round",
            "admission_track_code",
            "program_code",
            name="uq_admission_result_staging_rows_business_key",
        ),
        CheckConstraint("source_row_number > 0", name="source_row_number_positive"),
        CheckConstraint("academic_year IS NULL OR academic_year >= 2000", name="year_valid"),
        CheckConstraint("validation_status IN ('VALID', 'ERROR')", name="status_valid"),
        CheckConstraint(
            "validation_status != 'VALID' OR (academic_year IS NOT NULL "
            "AND university_code IS NOT NULL AND campus_code IS NOT NULL "
            "AND admission_round IS NOT NULL AND admission_track_code IS NOT NULL "
            "AND program_code IS NOT NULL)",
            name="valid_row_has_business_key",
        ),
        CheckConstraint("applicant_count IS NULL OR applicant_count >= 0", name="applicants_valid"),
        CheckConstraint("admitted_count IS NULL OR admitted_count >= 0", name="admitted_valid"),
        CheckConstraint(
            "competition_rate IS NULL OR competition_rate >= 0", name="competition_rate_valid"
        ),
        CheckConstraint("highest_score IS NULL OR highest_score >= 0", name="highest_score_valid"),
        CheckConstraint("average_score IS NULL OR average_score >= 0", name="average_score_valid"),
        CheckConstraint("lowest_score IS NULL OR lowest_score >= 0", name="lowest_score_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    staging_batch_id: Mapped[str] = mapped_column(
        ForeignKey("admission_result_staging_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    academic_year: Mapped[int | None] = mapped_column(Integer)
    university_code: Mapped[str | None] = mapped_column(String(80))
    campus_code: Mapped[str | None] = mapped_column(String(80))
    admission_round: Mapped[str | None] = mapped_column(String(80))
    admission_track_code: Mapped[str | None] = mapped_column(String(80))
    program_code: Mapped[str | None] = mapped_column(String(120))
    applicant_count: Mapped[int | None] = mapped_column(Integer)
    admitted_count: Mapped[int | None] = mapped_column(Integer)
    competition_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    highest_score: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    average_score: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    lowest_score: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    score_basis: Mapped[str | None] = mapped_column(String(80))
    validation_status: Mapped[str] = mapped_column(String(30), nullable=False)
    validation_issues: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list
    )


class AdmissionResultPublishedBatch(TimestampMixin, Base):
    __tablename__ = "admission_result_published_batches"
    __table_args__ = (
        CheckConstraint("confirmed_row_count > 0", name="confirmed_row_count_positive"),
        CheckConstraint("char_length(approved_by) > 0", name="approved_by_present"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    staging_batch_id: Mapped[str] = mapped_column(
        ForeignKey("admission_result_staging_batches.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    )
    approved_by: Mapped[str] = mapped_column(String(120), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_row_count: Mapped[int] = mapped_column(Integer, nullable=False)


class AdmissionResultPublished(TimestampMixin, Base):
    __tablename__ = "admission_results_published"
    __table_args__ = (
        UniqueConstraint("staging_row_id"),
        UniqueConstraint(
            "academic_year",
            "university_code",
            "campus_code",
            "admission_round",
            "admission_track_code",
            "program_code",
            "publication_version",
        ),
        CheckConstraint("academic_year >= 2000", name="academic_year_valid"),
        CheckConstraint("lifecycle_status IN ('PUBLISHED', 'SUPERSEDED')", name="status_valid"),
        CheckConstraint("applicant_count IS NULL OR applicant_count >= 0", name="applicants_valid"),
        CheckConstraint("admitted_count IS NULL OR admitted_count >= 0", name="admitted_valid"),
        CheckConstraint(
            "competition_rate IS NULL OR competition_rate >= 0", name="competition_rate_valid"
        ),
        CheckConstraint("highest_score IS NULL OR highest_score >= 0", name="highest_score_valid"),
        CheckConstraint("average_score IS NULL OR average_score >= 0", name="average_score_valid"),
        CheckConstraint("lowest_score IS NULL OR lowest_score >= 0", name="lowest_score_valid"),
        CheckConstraint(
            "(score_rule_id IS NULL AND score_rule_version IS NULL "
            "AND score_rule_academic_year IS NULL) OR "
            "(score_rule_id IS NOT NULL AND score_rule_version IS NOT NULL "
            "AND score_rule_academic_year = academic_year)",
            name="historical_rule_version_consistent",
        ),
        Index(
            "uq_admission_results_one_published_per_business_key",
            "academic_year",
            "university_code",
            "campus_code",
            "admission_round",
            "admission_track_code",
            "program_code",
            unique=True,
            postgresql_where=text("lifecycle_status = 'PUBLISHED'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    published_batch_id: Mapped[str] = mapped_column(
        ForeignKey("admission_result_published_batches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    staging_row_id: Mapped[str] = mapped_column(
        ForeignKey("admission_result_staging_rows.id", ondelete="RESTRICT"), nullable=False
    )
    academic_year: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    university_code: Mapped[str] = mapped_column(String(80), nullable=False)
    campus_code: Mapped[str] = mapped_column(String(80), nullable=False)
    admission_round: Mapped[str] = mapped_column(String(80), nullable=False)
    admission_track_code: Mapped[str] = mapped_column(String(80), nullable=False)
    program_code: Mapped[str] = mapped_column(String(120), nullable=False)
    publication_version: Mapped[str] = mapped_column(String(120), nullable=False)
    lifecycle_status: Mapped[str] = mapped_column(String(30), nullable=False, default="PUBLISHED")
    supersedes_id: Mapped[str | None] = mapped_column(
        ForeignKey("admission_results_published.id", ondelete="RESTRICT")
    )
    applicant_count: Mapped[int | None] = mapped_column(Integer)
    admitted_count: Mapped[int | None] = mapped_column(Integer)
    competition_rate: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    highest_score: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    average_score: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    lowest_score: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    score_basis: Mapped[str | None] = mapped_column(String(80))
    score_rule_id: Mapped[str | None] = mapped_column(
        ForeignKey("score_rules.id", ondelete="RESTRICT"), index=True
    )
    score_rule_version: Mapped[str | None] = mapped_column(String(120))
    score_rule_academic_year: Mapped[int | None] = mapped_column(Integer)


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
    "RuleAuditEvent",
    "RuleVersionLineage",
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
