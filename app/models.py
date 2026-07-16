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
    ForeignKeyConstraint,
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
    __table_args__ = (
        UniqueConstraint("code"),
        CheckConstraint(
            "code IS NULL OR (code = btrim(code) AND char_length(code) > 0)",
            name="code_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str | None] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    institution_type: Mapped[str] = mapped_column(String(40), nullable=False)


class Campus(TimestampMixin, Base):
    __tablename__ = "campuses"
    __table_args__ = (
        UniqueConstraint("institution_id", "name"),
        UniqueConstraint("institution_id", "code", name="uq_campuses_institution_id_code"),
        CheckConstraint(
            "code IS NULL OR (code = btrim(code) AND char_length(code) > 0)",
            name="code_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    code: Mapped[str | None] = mapped_column(String(80))
    institution_id: Mapped[str] = mapped_column(
        ForeignKey("institutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class Program(TimestampMixin, Base):
    __tablename__ = "programs"
    __table_args__ = (
        UniqueConstraint("campus_id", "name", name="uq_programs_campus_id"),
        UniqueConstraint("campus_id", "code", name="uq_programs_campus_id_code"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    campus_id: Mapped[str] = mapped_column(
        ForeignKey("campuses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str | None] = mapped_column(String(120))
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
    __table_args__ = (
        UniqueConstraint("rule_type", "rule_id", "review_kind", "reviewer_ref"),
        UniqueConstraint(
            "id",
            "rule_type",
            "rule_id",
            name="uq_rule_reviews_id_rule_type_rule_id",
        ),
        CheckConstraint(
            "payload_digest IS NULL OR char_length(payload_digest) = 64",
            name="payload_digest_valid",
        ),
        CheckConstraint(
            "contract_digest IS NULL OR char_length(contract_digest) = 64",
            name="contract_digest_valid",
        ),
        CheckConstraint(
            "contract_schema_version IS NULL OR contract_schema_version > 0",
            name="contract_schema_version_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rule_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    review_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    review_status: Mapped[str] = mapped_column(String(30), nullable=False)
    reviewer_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    payload_digest: Mapped[str | None] = mapped_column(String(64))
    contract_digest: Mapped[str | None] = mapped_column(String(64))
    contract_schema_version: Mapped[int | None] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


class RuleGoldenTestArtifact(TimestampMixin, Base):
    __tablename__ = "rule_golden_test_artifacts"
    __table_args__ = (
        UniqueConstraint("artifact_ref"),
        UniqueConstraint(
            "artifact_ref",
            "rule_id",
            name="uq_rule_golden_test_artifacts_artifact_ref_rule_id",
        ),
        UniqueConstraint(
            "artifact_ref",
            "rule_id",
            "rule_type",
            name="uq_rule_golden_test_artifacts_artifact_ref_rule_id_rule_type",
        ),
        CheckConstraint(
            "result_status IN ('PASSED', 'FAILED')",
            name="result_status_valid",
        ),
        CheckConstraint(
            "rule_type IN ('ADMISSION_ELIGIBILITY_RULE', 'GRADE_SOURCE_SCOPE_RULE', "
            "'SCORE_RULE', 'MULTIPLE_APPLICATION_RULE', 'DISQUALIFICATION_RULE', "
            "'SCORE_ADJUSTMENT_RULE', 'DOCUMENT_REQUIREMENT', 'TIE_BREAK_RULE')",
            name="rule_type_valid",
        ),
        CheckConstraint("artifact_digest ~ '^[0-9a-f]{64}$'", name="artifact_digest_valid"),
        CheckConstraint("payload_digest ~ '^[0-9a-f]{64}$'", name="payload_digest_valid"),
        CheckConstraint("contract_digest ~ '^[0-9a-f]{64}$'", name="contract_digest_valid"),
        CheckConstraint("suite_digest ~ '^[0-9a-f]{64}$'", name="suite_digest_valid"),
        CheckConstraint(
            "contract_schema_version = 2",
            name="contract_schema_version_valid",
        ),
        CheckConstraint(
            "artifact_ref = btrim(artifact_ref) AND char_length(artifact_ref) > 0",
            name="artifact_ref_present",
        ),
        CheckConstraint(
            "substr(artifact_ref, 1, char_length('golden-run/' || rule_type || '/')) "
            "= 'golden-run/' || rule_type || '/'",
            name="artifact_ref_rule_type",
        ),
        CheckConstraint(
            "suite_ref = btrim(suite_ref) AND char_length(suite_ref) > 0",
            name="suite_ref_present",
        ),
        CheckConstraint(
            "runner_ref = btrim(runner_ref) AND char_length(runner_ref) > 0",
            name="runner_present",
        ),
        CheckConstraint("case_count > 0", name="case_count_positive"),
        CheckConstraint(
            "passed_case_count >= 0 AND failed_case_count >= 0",
            name="case_counts_nonnegative",
        ),
        CheckConstraint(
            "passed_case_count + failed_case_count = case_count",
            name="case_counts_complete",
        ),
        CheckConstraint(
            "(result_status = 'PASSED' AND failed_case_count = 0 "
            "AND passed_case_count = case_count) OR "
            "(result_status = 'FAILED' AND failed_case_count > 0)",
            name="result_counts_consistent",
        ),
        ForeignKeyConstraint(
            ["independent_review_id", "rule_type", "rule_id"],
            ["rule_reviews.id", "rule_reviews.rule_type", "rule_reviews.rule_id"],
            ondelete="RESTRICT",
        ),
        Index("ix_rule_golden_test_artifacts_rule_type_rule_id", "rule_type", "rule_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    rule_type: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(36), nullable=False)
    independent_review_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    artifact_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    artifact_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    contract_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    suite_ref: Mapped[str] = mapped_column(String(240), nullable=False)
    suite_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    result_status: Mapped[str] = mapped_column(String(20), nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    passed_case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    failed_case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    runner_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


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
            "action IN ('DRAFT_CREATED', 'DRAFT_CLONED', 'DRAFT_UPDATED', 'EXTRACTED', "
            "'VERIFIED', 'TESTED', 'HUMAN_APPROVED', 'PUBLISHED', 'SUPERSEDED', "
            "'REJECTED')",
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
    golden_test_rule_type: Mapped[str | None] = mapped_column(String(80))
    human_approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def rule_constraints(
    rule_type: str,
) -> tuple[
    CheckConstraint,
    CheckConstraint,
    CheckConstraint,
    UniqueConstraint,
    ForeignKeyConstraint,
]:
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
        CheckConstraint(
            "(golden_test_ref IS NULL AND golden_test_rule_type IS NULL) OR "
            "(golden_test_ref IS NOT NULL AND golden_test_rule_type IS NOT NULL AND "
            f"golden_test_rule_type = '{rule_type}' AND "
            f"substr(golden_test_ref, 1, char_length('golden-run/{rule_type}/')) "
            f"= 'golden-run/{rule_type}/')",
            name="golden_test_rule_type",
        ),
        UniqueConstraint("admission_track_id", "version"),
        ForeignKeyConstraint(
            ["golden_test_ref", "id", "golden_test_rule_type"],
            [
                "rule_golden_test_artifacts.artifact_ref",
                "rule_golden_test_artifacts.rule_id",
                "rule_golden_test_artifacts.rule_type",
            ],
            ondelete="RESTRICT",
        ),
    )


class AdmissionEligibilityRule(RuleRecordMixin, Base):
    __tablename__ = "admission_eligibility_rules"
    __table_args__ = (
        *rule_constraints("ADMISSION_ELIGIBILITY_RULE"),
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
        *rule_constraints("GRADE_SOURCE_SCOPE_RULE"),
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
        *rule_constraints("SCORE_RULE"),
        CheckConstraint(
            "(admission_year IS NULL AND university_code IS NULL AND campus_code IS NULL "
            "AND admission_round IS NULL AND admission_track_code IS NULL) OR "
            "(admission_year IS NOT NULL AND university_code IS NOT NULL "
            "AND campus_code IS NOT NULL AND admission_round IS NOT NULL "
            "AND admission_track_code IS NOT NULL)",
            name="business_key_complete",
        ),
        UniqueConstraint(
            "admission_year",
            "university_code",
            "campus_code",
            "admission_round",
            "admission_track_code",
            "version",
            name="business_key_version",
        ),
        Index(
            "uq_score_rules_one_published_per_track",
            "admission_track_id",
            unique=True,
            postgresql_where=text("lifecycle_status = 'PUBLISHED'"),
        ),
        Index(
            "uq_score_rules_one_published_per_business_key",
            "admission_year",
            "university_code",
            "campus_code",
            "admission_round",
            "admission_track_code",
            unique=True,
            postgresql_where=text("lifecycle_status = 'PUBLISHED' AND admission_year IS NOT NULL"),
        ),
    )

    admission_year: Mapped[int | None] = mapped_column(Integer, index=True)
    university_code: Mapped[str | None] = mapped_column(String(80))
    university_name: Mapped[str | None] = mapped_column(String(200))
    campus_code: Mapped[str | None] = mapped_column(String(80))
    admission_round: Mapped[str | None] = mapped_column(String(80))
    admission_track_code: Mapped[str | None] = mapped_column(String(80))
    admission_track_name: Mapped[str | None] = mapped_column(String(200))
    evidence_document_ref: Mapped[str | None] = mapped_column(String(200))
    evidence_page: Mapped[int | None] = mapped_column(Integer)
    evidence_location: Mapped[str | None] = mapped_column(String(240))
    source_status: Mapped[str | None] = mapped_column(String(40))
    change_reason: Mapped[str | None] = mapped_column(Text)
    administrator_note: Mapped[str | None] = mapped_column(Text)


class MultipleApplicationRule(RuleRecordMixin, Base):
    __tablename__ = "multiple_application_rules"
    __table_args__ = (
        *rule_constraints("MULTIPLE_APPLICATION_RULE"),
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
        *rule_constraints("DISQUALIFICATION_RULE"),
        Index(
            "uq_disqualification_rules_one_published_per_track",
            "admission_track_id",
            unique=True,
            postgresql_where=text("lifecycle_status = 'PUBLISHED'"),
        ),
    )


class ScoreAdjustmentRule(RuleRecordMixin, Base):
    __tablename__ = "score_adjustment_rules"
    __table_args__ = rule_constraints("SCORE_ADJUSTMENT_RULE")


class DocumentRequirement(RuleRecordMixin, Base):
    __tablename__ = "document_requirements"
    __table_args__ = rule_constraints("DOCUMENT_REQUIREMENT")


class TieBreakRule(RuleRecordMixin, Base):
    __tablename__ = "tie_break_rules"
    __table_args__ = rule_constraints("TIE_BREAK_RULE")


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


class UserAccount(TimestampMixin, Base):
    __tablename__ = "user_accounts"
    __table_args__ = (
        UniqueConstraint("login_name"),
        UniqueConstraint("email"),
        UniqueConstraint("actor_ref"),
        CheckConstraint(
            "role IN ('ADMIN', 'ASSISTANT_ADMIN', 'MEMBER')",
            name="role_valid",
        ),
        CheckConstraint(
            "status IN ('PENDING_APPROVAL', 'ACTIVE', 'REJECTED', 'SUSPENDED')",
            name="status_valid",
        ),
        CheckConstraint("auth_version > 0", name="auth_version_positive"),
        CheckConstraint(
            "email = btrim(lower(email)) AND char_length(email) BETWEEN 3 AND 320",
            name="email_normalized",
        ),
        CheckConstraint(
            "display_name = btrim(display_name) AND char_length(display_name) BETWEEN 1 AND 120",
            name="display_name_valid",
        ),
        CheckConstraint(
            "actor_ref = btrim(actor_ref) AND char_length(actor_ref) BETWEEN 1 AND 120",
            name="actor_ref_valid",
        ),
        CheckConstraint(
            "(login_name IS NULL AND password_hash IS NULL) OR "
            "(login_name IS NOT NULL AND password_hash IS NOT NULL AND "
            "login_name = btrim(lower(login_name)) AND char_length(login_name) BETWEEN 4 AND 80 "
            "AND char_length(password_hash) > 0)",
            name="local_credentials_complete",
        ),
        CheckConstraint(
            "status NOT IN ('PENDING_APPROVAL', 'REJECTED') OR role = 'MEMBER'",
            name="pending_role_member",
        ),
        CheckConstraint(
            "(status IN ('PENDING_APPROVAL', 'REJECTED') AND approved_at IS NULL "
            "AND approved_by_user_id IS NULL) OR "
            "(status IN ('ACTIVE', 'SUSPENDED') AND approved_at IS NOT NULL "
            "AND approved_by_user_id IS NOT NULL)",
            name="approval_state_consistent",
        ),
        Index("ix_user_accounts_status_role", "status", "role"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    login_name: Mapped[str | None] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(30), nullable=False, default="MEMBER")
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PENDING_APPROVAL", index=True
    )
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExternalIdentity(TimestampMixin, Base):
    __tablename__ = "external_identities"
    __table_args__ = (
        UniqueConstraint("provider", "issuer", "provider_subject"),
        UniqueConstraint("user_account_id", "provider"),
        CheckConstraint("provider = 'GOOGLE'", name="provider_valid"),
        CheckConstraint(
            "issuer = 'https://accounts.google.com'",
            name="issuer_valid",
        ),
        CheckConstraint(
            "provider_subject = btrim(provider_subject) "
            "AND char_length(provider_subject) BETWEEN 1 AND 255",
            name="provider_subject_valid",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_account_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    issuer: Mapped[str] = mapped_column(String(200), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)


class UserAccountAuditEvent(TimestampMixin, Base):
    __tablename__ = "user_account_audit_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('REGISTERED_LOCAL', 'REGISTERED_GOOGLE', "
            "'BOOTSTRAPPED_ADMIN', 'APPROVED', 'ROLE_CHANGED', 'STATUS_CHANGED', "
            "'LOGIN_SUCCEEDED', 'PASSWORD_CHANGED')",
            name="event_type_valid",
        ),
        CheckConstraint(
            "before_role IS NULL OR before_role IN ('ADMIN', 'ASSISTANT_ADMIN', 'MEMBER')",
            name="before_role_valid",
        ),
        CheckConstraint(
            "after_role IS NULL OR after_role IN ('ADMIN', 'ASSISTANT_ADMIN', 'MEMBER')",
            name="after_role_valid",
        ),
        CheckConstraint(
            "before_status IS NULL OR before_status IN "
            "('PENDING_APPROVAL', 'ACTIVE', 'REJECTED', 'SUSPENDED')",
            name="before_status_valid",
        ),
        CheckConstraint(
            "after_status IS NULL OR after_status IN "
            "('PENDING_APPROVAL', 'ACTIVE', 'REJECTED', 'SUSPENDED')",
            name="after_status_valid",
        ),
        Index("ix_user_account_audit_events_target_occurred", "target_user_id", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    target_user_id: Mapped[str] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("user_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    before_role: Mapped[str | None] = mapped_column(String(30))
    after_role: Mapped[str | None] = mapped_column(String(30))
    before_status: Mapped[str | None] = mapped_column(String(30))
    after_status: Mapped[str | None] = mapped_column(String(30))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class AiProviderCredential(TimestampMixin, Base):
    __tablename__ = "ai_provider_credentials"
    __table_args__ = (
        UniqueConstraint("actor_ref", "provider"),
        CheckConstraint(
            "provider IN ('OPENAI', 'GEMINI', 'ANTHROPIC')",
            name="provider_valid",
        ),
        CheckConstraint("char_length(actor_ref) > 0", name="actor_present"),
        CheckConstraint("char_length(encrypted_api_key) > 0", name="ciphertext_present"),
        CheckConstraint("char_length(masked_hint) = 8", name="masked_hint_valid"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_ref: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    encrypted_api_key: Mapped[str] = mapped_column(Text, nullable=False)
    masked_hint: Mapped[str] = mapped_column(String(8), nullable=False)
    encryption_version: Mapped[str] = mapped_column(String(30), nullable=False)


class AiConsultationDraft(TimestampMixin, Base):
    __tablename__ = "ai_consultation_drafts"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('OPENAI', 'GEMINI', 'ANTHROPIC')",
            name="provider_valid",
        ),
        CheckConstraint(
            "status IN ('GENERATED_DRAFT', 'TEACHER_CONFIRMED', 'REJECTED')",
            name="status_valid",
        ),
        CheckConstraint("char_length(actor_ref) > 0", name="actor_present"),
        CheckConstraint("char_length(payload_digest) = 64", name="payload_digest_valid"),
        CheckConstraint(
            "(status = 'TEACHER_CONFIRMED' AND teacher_text IS NOT NULL "
            "AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL) OR "
            "(status IN ('GENERATED_DRAFT', 'REJECTED') AND teacher_text IS NULL "
            "AND confirmed_by IS NULL AND confirmed_at IS NULL)",
            name="confirmed_draft_complete",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_ref: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    generated_text: Mapped[str] = mapped_column(Text, nullable=False)
    check_items: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    teacher_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="GENERATED_DRAFT")
    confirmed_by: Mapped[str | None] = mapped_column(String(120))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


__all__ = [
    "AiConsultationDraft",
    "AiProviderCredential",
    "AdmissionEligibilityRule",
    "AdmissionRound",
    "AdmissionTrack",
    "AssessmentComponent",
    "Campus",
    "DisqualificationRule",
    "DocumentRequirement",
    "ExternalIdentity",
    "GradeSourceScopeRule",
    "ImportBatch",
    "Institution",
    "MultipleApplicationRule",
    "Program",
    "RuleReview",
    "RuleGoldenTestArtifact",
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
    "UserAccount",
    "UserAccountAuditEvent",
    "VocationalCourseReport",
    "VocationalCourseStatistic",
    "VocationalStudentResult",
]
