from __future__ import annotations

import shutil
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError

from app import create_app

CANONICAL_GATE_HEAD = "0d9f4a7c2b11"
CANONICAL_GATE_PARENT = "f76a91c3d2e8"
TESTED_AUDIT_PARENT = "e51f0b24c8aa"
MEMBERSHIP_HEAD = "6c1a2e9f4b73"
MEMBERSHIP_PARENT = CANONICAL_GATE_HEAD
REPOSITORY_HEAD = MEMBERSHIP_HEAD
RULE_TABLE_TYPES_WITH_GOLDEN_ARTIFACT = (
    ("admission_eligibility_rules", "ADMISSION_ELIGIBILITY_RULE"),
    ("grade_source_scope_rules", "GRADE_SOURCE_SCOPE_RULE"),
    ("score_rules", "SCORE_RULE"),
    ("multiple_application_rules", "MULTIPLE_APPLICATION_RULE"),
    ("disqualification_rules", "DISQUALIFICATION_RULE"),
    ("score_adjustment_rules", "SCORE_ADJUSTMENT_RULE"),
    ("document_requirements", "DOCUMENT_REQUIREMENT"),
    ("tie_break_rules", "TIE_BREAK_RULE"),
)


def _insert_rule_review(connection: Connection, *, review_id: str, rule_id: str) -> None:
    connection.execute(
        text(
            """
            INSERT INTO rule_reviews (
                id, rule_type, rule_id, review_kind, review_status,
                reviewer_ref, reviewed_at
            ) VALUES (
                :id, 'SCORE_RULE', :rule_id, 'INDEPENDENT_VERIFICATION',
                'APPROVED', :reviewer_ref, :reviewed_at
            )
            """
        ),
        {
            "id": review_id,
            "rule_id": rule_id,
            "reviewer_ref": f"synthetic-reviewer-{review_id}",
            "reviewed_at": datetime(2026, 7, 15, tzinfo=UTC),
        },
    )


def _artifact_values(
    *,
    artifact_id: str,
    artifact_ref: str,
    review_id: str,
    rule_id: str,
    **overrides: object,
) -> dict[str, object]:
    values: dict[str, object] = {
        "id": artifact_id,
        "rule_type": "SCORE_RULE",
        "rule_id": rule_id,
        "independent_review_id": review_id,
        "artifact_ref": artifact_ref,
        "artifact_digest": "a" * 64,
        "suite_ref": "tests/synthetic::canonical-gate",
        "suite_digest": "b" * 64,
        "case_count": 2,
        "passed_case_count": 2,
        "failed_case_count": 0,
        "payload_digest": "c" * 64,
        "contract_digest": "d" * 64,
        "contract_schema_version": 2,
        "result_status": "PASSED",
        "runner_ref": "synthetic-runner-v1",
        "executed_at": datetime(2026, 7, 15, tzinfo=UTC),
    }
    values.update(overrides)
    return values


def _insert_artifact(connection: Connection, values: dict[str, object]) -> None:
    connection.execute(
        text(
            """
            INSERT INTO rule_golden_test_artifacts (
                id, rule_type, rule_id, independent_review_id,
                artifact_ref, artifact_digest, suite_ref, suite_digest,
                case_count, passed_case_count, failed_case_count,
                payload_digest, contract_digest, contract_schema_version, result_status,
                runner_ref, executed_at
            ) VALUES (
                :id, :rule_type, :rule_id, :independent_review_id,
                :artifact_ref, :artifact_digest, :suite_ref, :suite_digest,
                :case_count, :passed_case_count, :failed_case_count,
                :payload_digest, :contract_digest, :contract_schema_version, :result_status,
                :runner_ref, :executed_at
            )
            """
        ),
        values,
    )


def test_alembic_upgrade_creates_phase_one_schema(postgres_engine: Engine) -> None:
    assert postgres_engine.dialect.name == "postgresql"
    tables = set(inspect(postgres_engine).get_table_names())
    required = {
        "admission_eligibility_rules",
        "admission_result_published_batches",
        "admission_result_raw_batches",
        "admission_result_raw_pages",
        "admission_result_staging_batches",
        "admission_result_staging_rows",
        "admission_results_published",
        "admission_rounds",
        "admission_tracks",
        "alembic_version",
        "assessment_components",
        "ai_consultation_drafts",
        "ai_provider_credentials",
        "campuses",
        "disqualification_rules",
        "document_requirements",
        "external_identities",
        "grade_source_scope_rules",
        "import_batches",
        "institutions",
        "multiple_application_rules",
        "programs",
        "rule_reviews",
        "rule_audit_events",
        "rule_golden_test_artifacts",
        "rule_version_lineages",
        "score_adjustment_rules",
        "score_rules",
        "source_citations",
        "source_document_pages",
        "source_documents",
        "student_academic_records",
        "student_course_records",
        "tie_break_rules",
        "user_account_audit_events",
        "user_accounts",
        "vocational_course_reports",
        "vocational_course_statistics",
        "vocational_student_results",
    }

    assert required <= tables
    course_checks = {
        constraint["name"]
        for constraint in inspect(postgres_engine).get_check_constraints("student_course_records")
    }
    assert {
        "ck_student_course_records_raw_score_label_valid",
        "ck_student_course_records_raw_score_value_or_label",
    } <= course_checks
    for table_name in (
        "admission_eligibility_rules",
        "multiple_application_rules",
        "disqualification_rules",
        "grade_source_scope_rules",
        "score_rules",
    ):
        index_names = {index["name"] for index in inspect(postgres_engine).get_indexes(table_name)}
        assert f"uq_{table_name}_one_published_per_track" in index_names
    result_indexes = {
        index["name"]
        for index in inspect(postgres_engine).get_indexes("admission_results_published")
    }
    assert "uq_admission_results_one_published_per_business_key" in result_indexes
    audit_checks = {
        constraint["name"]: constraint["sqltext"]
        for constraint in inspect(postgres_engine).get_check_constraints("rule_audit_events")
    }
    action_check = audit_checks["ck_rule_audit_events_action_valid"]
    assert all(action in action_check for action in ("EXTRACTED", "VERIFIED", "TESTED"))
    review_columns = {
        column["name"]: column for column in inspect(postgres_engine).get_columns("rule_reviews")
    }
    assert {
        "payload_digest",
        "contract_digest",
        "contract_schema_version",
    } <= review_columns.keys()
    assert review_columns["contract_schema_version"]["nullable"] is True
    review_checks = {
        constraint["name"]
        for constraint in inspect(postgres_engine).get_check_constraints("rule_reviews")
    }
    assert "ck_rule_reviews_payload_digest_valid" in review_checks
    assert "ck_rule_reviews_contract_digest_valid" in review_checks
    assert "ck_rule_reviews_contract_schema_version_valid" in review_checks

    institution_columns = {
        column["name"]: column for column in inspect(postgres_engine).get_columns("institutions")
    }
    campus_columns = {
        column["name"]: column for column in inspect(postgres_engine).get_columns("campuses")
    }
    assert institution_columns["code"]["nullable"] is True
    assert campus_columns["code"]["nullable"] is True
    institution_uniques = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspect(postgres_engine).get_unique_constraints("institutions")
    }
    campus_uniques = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspect(postgres_engine).get_unique_constraints("campuses")
    }
    assert institution_uniques["uq_institutions_code"] == ("code",)
    assert campus_uniques["uq_campuses_institution_id_code"] == (
        "institution_id",
        "code",
    )
    institution_checks = {
        constraint["name"]
        for constraint in inspect(postgres_engine).get_check_constraints("institutions")
    }
    campus_checks = {
        constraint["name"]
        for constraint in inspect(postgres_engine).get_check_constraints("campuses")
    }
    assert "ck_institutions_code_valid" in institution_checks
    assert "ck_campuses_code_valid" in campus_checks

    artifact_columns = {
        column["name"]: column
        for column in inspect(postgres_engine).get_columns("rule_golden_test_artifacts")
    }
    assert {
        "artifact_ref",
        "artifact_digest",
        "suite_ref",
        "suite_digest",
        "case_count",
        "passed_case_count",
        "failed_case_count",
        "payload_digest",
        "contract_digest",
        "contract_schema_version",
        "result_status",
        "runner_ref",
        "executed_at",
    } <= artifact_columns.keys()
    assert artifact_columns["contract_schema_version"]["nullable"] is False
    artifact_checks = {
        constraint["name"]
        for constraint in inspect(postgres_engine).get_check_constraints(
            "rule_golden_test_artifacts"
        )
    }
    assert {
        "ck_rule_golden_test_artifacts_artifact_digest_valid",
        "ck_rule_golden_test_artifacts_artifact_ref_present",
        "ck_rule_golden_test_artifacts_artifact_ref_rule_type",
        "ck_rule_golden_test_artifacts_case_count_positive",
        "ck_rule_golden_test_artifacts_case_counts_complete",
        "ck_rule_golden_test_artifacts_case_counts_nonnegative",
        "ck_rule_golden_test_artifacts_contract_digest_valid",
        "ck_rule_golden_test_artifacts_contract_schema_version_valid",
        "ck_rule_golden_test_artifacts_payload_digest_valid",
        "ck_rule_golden_test_artifacts_result_counts_consistent",
        "ck_rule_golden_test_artifacts_result_status_valid",
        "ck_rule_golden_test_artifacts_rule_type_valid",
        "ck_rule_golden_test_artifacts_runner_present",
        "ck_rule_golden_test_artifacts_suite_digest_valid",
        "ck_rule_golden_test_artifacts_suite_ref_present",
    } <= artifact_checks
    artifact_uniques = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspect(postgres_engine).get_unique_constraints(
            "rule_golden_test_artifacts"
        )
    }
    assert artifact_uniques["uq_rule_golden_test_artifacts_artifact_ref"] == ("artifact_ref",)
    assert artifact_uniques["uq_rule_golden_test_artifacts_artifact_ref_rule_id"] == (
        "artifact_ref",
        "rule_id",
    )
    assert artifact_uniques["uq_rule_golden_test_artifacts_artifact_ref_rule_id_rule_type"] == (
        "artifact_ref",
        "rule_id",
        "rule_type",
    )
    review_uniques = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspect(postgres_engine).get_unique_constraints("rule_reviews")
    }
    assert review_uniques["uq_rule_reviews_id_rule_type_rule_id"] == (
        "id",
        "rule_type",
        "rule_id",
    )
    artifact_foreign_keys = inspect(postgres_engine).get_foreign_keys("rule_golden_test_artifacts")
    assert any(
        tuple(foreign_key["constrained_columns"])
        == ("independent_review_id", "rule_type", "rule_id")
        and foreign_key["referred_table"] == "rule_reviews"
        and tuple(foreign_key["referred_columns"]) == ("id", "rule_type", "rule_id")
        and foreign_key["options"].get("ondelete") == "RESTRICT"
        for foreign_key in artifact_foreign_keys
    )
    artifact_indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspect(postgres_engine).get_indexes("rule_golden_test_artifacts")
    }
    assert artifact_indexes["ix_rule_golden_test_artifacts_independent_review_id"] == (
        "independent_review_id",
    )
    assert artifact_indexes["ix_rule_golden_test_artifacts_rule_type_rule_id"] == (
        "rule_type",
        "rule_id",
    )
    for table_name, _rule_type in RULE_TABLE_TYPES_WITH_GOLDEN_ARTIFACT:
        rule_columns = {
            column["name"]: column for column in inspect(postgres_engine).get_columns(table_name)
        }
        assert rule_columns["golden_test_rule_type"]["nullable"] is True
        rule_checks = {
            constraint["name"]
            for constraint in inspect(postgres_engine).get_check_constraints(table_name)
        }
        assert f"ck_{table_name}_golden_test_rule_type" in rule_checks
        rule_foreign_keys = inspect(postgres_engine).get_foreign_keys(table_name)
        assert any(
            tuple(foreign_key["constrained_columns"])
            == ("golden_test_ref", "id", "golden_test_rule_type")
            and foreign_key["referred_table"] == "rule_golden_test_artifacts"
            and tuple(foreign_key["referred_columns"]) == ("artifact_ref", "rule_id", "rule_type")
            and foreign_key["options"].get("ondelete") == "RESTRICT"
            for foreign_key in rule_foreign_keys
        )


def test_membership_schema_contract(postgres_engine: Engine) -> None:
    inspector = inspect(postgres_engine)
    account_columns = {column["name"]: column for column in inspector.get_columns("user_accounts")}
    assert {
        "id",
        "actor_ref",
        "login_name",
        "email",
        "display_name",
        "password_hash",
        "role",
        "status",
        "auth_version",
        "approved_by_user_id",
        "approved_at",
        "last_login_at",
        "created_at",
        "updated_at",
    } == account_columns.keys()
    assert account_columns["login_name"]["nullable"] is True
    assert account_columns["actor_ref"]["nullable"] is False
    assert account_columns["password_hash"]["nullable"] is True
    assert account_columns["email"]["nullable"] is False
    assert account_columns["role"]["nullable"] is False
    assert account_columns["status"]["nullable"] is False
    assert account_columns["auth_version"]["nullable"] is False

    account_checks = {
        constraint["name"]: constraint["sqltext"]
        for constraint in inspector.get_check_constraints("user_accounts")
    }
    assert {
        "ck_user_accounts_approval_state_consistent",
        "ck_user_accounts_auth_version_positive",
        "ck_user_accounts_actor_ref_valid",
        "ck_user_accounts_display_name_valid",
        "ck_user_accounts_email_normalized",
        "ck_user_accounts_local_credentials_complete",
        "ck_user_accounts_pending_role_member",
        "ck_user_accounts_role_valid",
        "ck_user_accounts_status_valid",
    } == account_checks.keys()
    assert "REJECTED" in account_checks["ck_user_accounts_pending_role_member"]
    assert (
        "approved_by_user_id IS NOT NULL"
        in account_checks["ck_user_accounts_approval_state_consistent"]
    )
    account_uniques = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("user_accounts")
    }
    assert account_uniques["uq_user_accounts_email"] == ("email",)
    assert account_uniques["uq_user_accounts_login_name"] == ("login_name",)
    assert account_uniques["uq_user_accounts_actor_ref"] == ("actor_ref",)
    account_foreign_keys = inspector.get_foreign_keys("user_accounts")
    assert any(
        tuple(foreign_key["constrained_columns"]) == ("approved_by_user_id",)
        and foreign_key["referred_table"] == "user_accounts"
        and tuple(foreign_key["referred_columns"]) == ("id",)
        and foreign_key["options"].get("ondelete") == "RESTRICT"
        for foreign_key in account_foreign_keys
    )
    account_indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes("user_accounts")
    }
    assert account_indexes["ix_user_accounts_approved_by_user_id"] == ("approved_by_user_id",)
    assert account_indexes["ix_user_accounts_status"] == ("status",)
    assert account_indexes["ix_user_accounts_status_role"] == ("status", "role")

    identity_columns = {
        column["name"]: column for column in inspector.get_columns("external_identities")
    }
    assert {
        "id",
        "user_account_id",
        "provider",
        "issuer",
        "provider_subject",
        "created_at",
        "updated_at",
    } == identity_columns.keys()
    assert {
        "access_token",
        "refresh_token",
        "id_token",
        "authorization_code",
    }.isdisjoint(identity_columns)
    identity_checks = {
        constraint["name"]: constraint["sqltext"]
        for constraint in inspector.get_check_constraints("external_identities")
    }
    assert {
        "ck_external_identities_issuer_valid",
        "ck_external_identities_provider_subject_valid",
        "ck_external_identities_provider_valid",
    } == identity_checks.keys()
    assert "https://accounts.google.com" in identity_checks["ck_external_identities_issuer_valid"]
    identity_uniques = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("external_identities")
    }
    assert identity_uniques["uq_external_identities_provider"] == (
        "provider",
        "issuer",
        "provider_subject",
    )
    assert identity_uniques["uq_external_identities_user_account_id"] == (
        "user_account_id",
        "provider",
    )
    identity_foreign_keys = inspector.get_foreign_keys("external_identities")
    assert any(
        tuple(foreign_key["constrained_columns"]) == ("user_account_id",)
        and foreign_key["referred_table"] == "user_accounts"
        and tuple(foreign_key["referred_columns"]) == ("id",)
        and foreign_key["options"].get("ondelete") == "CASCADE"
        for foreign_key in identity_foreign_keys
    )

    audit_columns = {
        column["name"]: column for column in inspector.get_columns("user_account_audit_events")
    }
    assert {
        "id",
        "target_user_id",
        "actor_user_id",
        "event_type",
        "before_role",
        "after_role",
        "before_status",
        "after_status",
        "occurred_at",
        "details",
        "created_at",
        "updated_at",
    } == audit_columns.keys()
    assert audit_columns["target_user_id"]["nullable"] is False
    assert audit_columns["actor_user_id"]["nullable"] is True
    assert audit_columns["details"]["nullable"] is False
    audit_checks = {
        constraint["name"]
        for constraint in inspector.get_check_constraints("user_account_audit_events")
    }
    assert {
        "ck_user_account_audit_events_after_role_valid",
        "ck_user_account_audit_events_after_status_valid",
        "ck_user_account_audit_events_before_role_valid",
        "ck_user_account_audit_events_before_status_valid",
        "ck_user_account_audit_events_event_type_valid",
    } == audit_checks
    audit_foreign_keys = inspector.get_foreign_keys("user_account_audit_events")
    assert any(
        tuple(foreign_key["constrained_columns"]) == ("target_user_id",)
        and foreign_key["referred_table"] == "user_accounts"
        and foreign_key["options"].get("ondelete") == "RESTRICT"
        for foreign_key in audit_foreign_keys
    )
    assert any(
        tuple(foreign_key["constrained_columns"]) == ("actor_user_id",)
        and foreign_key["referred_table"] == "user_accounts"
        and foreign_key["options"].get("ondelete") == "SET NULL"
        for foreign_key in audit_foreign_keys
    )
    audit_indexes = {
        index["name"]: tuple(index["column_names"])
        for index in inspector.get_indexes("user_account_audit_events")
    }
    assert audit_indexes["ix_user_account_audit_events_actor_user_id"] == ("actor_user_id",)
    assert audit_indexes["ix_user_account_audit_events_target_user_id"] == ("target_user_id",)
    assert audit_indexes["ix_user_account_audit_events_target_occurred"] == (
        "target_user_id",
        "occurred_at",
    )


def test_canonical_code_constraints_are_enforced(postgres_engine: Engine) -> None:
    institution_id = str(uuid4())
    other_institution_id = str(uuid4())
    campus_id = str(uuid4())
    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(
                text(
                    "INSERT INTO institutions (id, code, name, institution_type) "
                    "VALUES (:id, 'SYNTHETIC_A', :name, 'JUNIOR_COLLEGE')"
                ),
                {"id": institution_id, "name": f"합성대학-{institution_id}"},
            )
            connection.execute(
                text(
                    "INSERT INTO institutions (id, code, name, institution_type) "
                    "VALUES (:id, 'SYNTHETIC_B', :name, 'JUNIOR_COLLEGE')"
                ),
                {
                    "id": other_institution_id,
                    "name": f"합성대학-{other_institution_id}",
                },
            )
            connection.execute(
                text(
                    "INSERT INTO campuses (id, institution_id, code, name) "
                    "VALUES (:id, :institution_id, 'MAIN', :name)"
                ),
                {
                    "id": campus_id,
                    "institution_id": institution_id,
                    "name": f"합성캠퍼스-{campus_id}",
                },
            )

            invalid_statements = (
                (
                    "INSERT INTO institutions (id, code, name, institution_type) "
                    "VALUES (:id, 'SYNTHETIC_A', :name, 'JUNIOR_COLLEGE')",
                    {"id": str(uuid4()), "name": f"중복대학-{uuid4()}"},
                ),
                (
                    "INSERT INTO institutions (id, code, name, institution_type) "
                    "VALUES (:id, ' PADDED ', :name, 'JUNIOR_COLLEGE')",
                    {"id": str(uuid4()), "name": f"공백대학-{uuid4()}"},
                ),
                (
                    "INSERT INTO campuses (id, institution_id, code, name) "
                    "VALUES (:id, :institution_id, 'MAIN', :name)",
                    {
                        "id": str(uuid4()),
                        "institution_id": institution_id,
                        "name": f"중복캠퍼스-{uuid4()}",
                    },
                ),
                (
                    "INSERT INTO campuses (id, institution_id, code, name) "
                    "VALUES (:id, :institution_id, ' PADDED ', :name)",
                    {
                        "id": str(uuid4()),
                        "institution_id": institution_id,
                        "name": f"공백캠퍼스-{uuid4()}",
                    },
                ),
            )
            for statement, parameters in invalid_statements:
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(text(statement), parameters)

            connection.execute(
                text(
                    "INSERT INTO campuses (id, institution_id, code, name) "
                    "VALUES (:id, :institution_id, 'MAIN', :name)"
                ),
                {
                    "id": str(uuid4()),
                    "institution_id": other_institution_id,
                    "name": f"다른대학캠퍼스-{uuid4()}",
                },
            )
        finally:
            transaction.rollback()


def test_golden_artifact_constraints_are_enforced(postgres_engine: Engine) -> None:
    review_id = str(uuid4())
    rule_id = str(uuid4())
    artifact_id = str(uuid4())
    valid_artifact_ref = f"golden-run/SCORE_RULE/{artifact_id}"
    with postgres_engine.connect() as connection:
        transaction = connection.begin()
        try:
            _insert_rule_review(connection, review_id=review_id, rule_id=rule_id)
            connection.execute(
                text("UPDATE rule_reviews SET contract_schema_version = 2 WHERE id = :review_id"),
                {"review_id": review_id},
            )
            for invalid_contract_schema_version in (0, -1):
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        text(
                            "UPDATE rule_reviews SET contract_schema_version = :version "
                            "WHERE id = :review_id"
                        ),
                        {
                            "review_id": review_id,
                            "version": invalid_contract_schema_version,
                        },
                    )
            _insert_artifact(
                connection,
                _artifact_values(
                    artifact_id=artifact_id,
                    artifact_ref=valid_artifact_ref,
                    review_id=review_id,
                    rule_id=rule_id,
                ),
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                _insert_artifact(
                    connection,
                    _artifact_values(
                        artifact_id=str(uuid4()),
                        artifact_ref=valid_artifact_ref,
                        review_id=review_id,
                        rule_id=rule_id,
                    ),
                )
            invalid_overrides = (
                {"artifact_digest": "x" * 64},
                {"suite_digest": "x" * 64},
                {
                    "rule_type": "SCORE_RULE/ALT",
                    "artifact_ref": f"golden-run/SCORE_RULE/ALT/{uuid4()}",
                },
                {"contract_schema_version": 1},
                {"contract_schema_version": 3},
                {"artifact_ref": " padded-artifact "},
                {"suite_ref": " padded-suite "},
                {"runner_ref": " padded-runner "},
                {"case_count": 0, "passed_case_count": 0, "failed_case_count": 0},
                {"case_count": 1, "passed_case_count": -1, "failed_case_count": 2},
                {"case_count": 2, "passed_case_count": 1, "failed_case_count": 0},
                {"case_count": 2, "passed_case_count": 1, "failed_case_count": 1},
                {
                    "case_count": 2,
                    "passed_case_count": 2,
                    "failed_case_count": 0,
                    "result_status": "FAILED",
                },
            )
            for overrides in invalid_overrides:
                invalid_artifact_id = str(uuid4())
                values = _artifact_values(
                    artifact_id=invalid_artifact_id,
                    artifact_ref=f"golden-run/SCORE_RULE/{invalid_artifact_id}",
                    review_id=review_id,
                    rule_id=rule_id,
                )
                values.update(overrides)
                with pytest.raises(IntegrityError), connection.begin_nested():
                    _insert_artifact(connection, values)

            mismatched_rule_id = str(uuid4())
            mismatched_artifact_id = str(uuid4())
            with pytest.raises(IntegrityError), connection.begin_nested():
                _insert_artifact(
                    connection,
                    _artifact_values(
                        artifact_id=mismatched_artifact_id,
                        artifact_ref=f"golden-run/SCORE_RULE/{mismatched_artifact_id}",
                        review_id=review_id,
                        rule_id=mismatched_rule_id,
                    ),
                )
            connection.execute(
                text(
                    """
                    INSERT INTO score_rules (
                        id, version, lifecycle_status, rule_payload,
                        independent_verified, golden_test_ref, golden_test_rule_type
                    ) VALUES (
                        :id, 'synthetic-artifact-fk-v1', 'DRAFT',
                        '{}'::json, FALSE, :artifact_ref, 'SCORE_RULE'
                    )
                    """
                ),
                {"id": rule_id, "artifact_ref": valid_artifact_ref},
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        """
                        INSERT INTO score_rules (
                            id, version, lifecycle_status, rule_payload,
                            independent_verified, golden_test_ref, golden_test_rule_type
                        ) VALUES (
                            :id, 'synthetic-cross-rule-artifact-v1', 'DRAFT',
                            '{}'::json, FALSE, :artifact_ref, 'SCORE_RULE'
                        )
                        """
                    ),
                    {"id": str(uuid4()), "artifact_ref": valid_artifact_ref},
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        """
                        INSERT INTO admission_eligibility_rules (
                            id, version, lifecycle_status, rule_payload,
                            independent_verified, golden_test_ref, golden_test_rule_type
                        ) VALUES (
                            :id, 'synthetic-cross-type-artifact-v1', 'DRAFT',
                            '{}'::json, FALSE, :artifact_ref, 'SCORE_RULE'
                        )
                        """
                    ),
                    {"id": rule_id, "artifact_ref": valid_artifact_ref},
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        """
                        INSERT INTO score_rules (
                            id, version, lifecycle_status, rule_payload,
                            independent_verified, golden_test_ref, golden_test_rule_type
                        ) VALUES (
                            :id, 'synthetic-missing-artifact-type-v1', 'DRAFT',
                            '{}'::json, FALSE, :artifact_ref, NULL
                        )
                        """
                    ),
                    {"id": str(uuid4()), "artifact_ref": valid_artifact_ref},
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        """
                        INSERT INTO score_rules (
                            id, version, lifecycle_status, rule_payload,
                            independent_verified, golden_test_ref, golden_test_rule_type
                        ) VALUES (
                            :id, 'synthetic-orphan-artifact-type-v1', 'DRAFT',
                            '{}'::json, FALSE, NULL, 'SCORE_RULE'
                        )
                        """
                    ),
                    {"id": str(uuid4())},
                )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text("DELETE FROM rule_golden_test_artifacts WHERE artifact_ref = :ref"),
                    {"ref": valid_artifact_ref},
                )
        finally:
            transaction.rollback()


def test_membership_downgrade_is_fail_closed_and_reversible_when_empty(
    postgres_engine: Engine,
) -> None:
    config = Config("alembic.ini")
    account_id = str(uuid4())

    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO user_accounts (
                    id, actor_ref, login_name, email, display_name, password_hash,
                    role, status, auth_version
                ) VALUES (
                    :id, :actor_ref, :login_name, :email, '합성 보존 회원',
                    'synthetic-password-hash', 'MEMBER', 'PENDING_APPROVAL', 1
                )
                """
            ),
            {
                "id": account_id,
                "actor_ref": f"user:{account_id}",
                "login_name": f"synthetic-{account_id}",
                "email": f"{account_id}@example.invalid",
            },
        )

    try:
        with pytest.raises(DBAPIError, match="회원 계정.*membership migration"):
            command.downgrade(config, MEMBERSHIP_PARENT)
        with postgres_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == MEMBERSHIP_HEAD
            )

        with postgres_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM user_accounts WHERE id = :id"),
                {"id": account_id},
            )
        command.downgrade(config, MEMBERSHIP_PARENT)
        downgraded_tables = set(inspect(postgres_engine).get_table_names())
        assert {
            "user_accounts",
            "external_identities",
            "user_account_audit_events",
        }.isdisjoint(downgraded_tables)

        command.upgrade(config, REPOSITORY_HEAD)
        assert {
            "user_accounts",
            "external_identities",
            "user_account_audit_events",
        } <= set(inspect(postgres_engine).get_table_names())
    finally:
        if "user_accounts" in set(inspect(postgres_engine).get_table_names()):
            with postgres_engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM user_accounts WHERE id = :id"),
                    {"id": account_id},
                )
        command.upgrade(config, REPOSITORY_HEAD)


def test_canonical_gate_downgrade_is_fail_closed_and_null_safe(
    postgres_engine: Engine,
) -> None:
    config = Config("alembic.ini")
    institution_id = str(uuid4())
    campus_id = str(uuid4())
    review_id = str(uuid4())
    rule_id = str(uuid4())
    legacy_rule_id = str(uuid4())
    artifact_id = str(uuid4())
    artifact_ref = f"golden-run/SCORE_RULE/{artifact_id}"

    with postgres_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO institutions (id, code, name, institution_type) "
                "VALUES (:id, NULL, :name, 'JUNIOR_COLLEGE')"
            ),
            {"id": institution_id, "name": f"합성보존대학-{institution_id}"},
        )
        connection.execute(
            text(
                "INSERT INTO campuses (id, institution_id, code, name) "
                "VALUES (:id, :institution_id, NULL, :name)"
            ),
            {
                "id": campus_id,
                "institution_id": institution_id,
                "name": f"합성보존캠퍼스-{campus_id}",
            },
        )
        _insert_rule_review(connection, review_id=review_id, rule_id=rule_id)
        _insert_artifact(
            connection,
            _artifact_values(
                artifact_id=artifact_id,
                artifact_ref=artifact_ref,
                review_id=review_id,
                rule_id=rule_id,
            ),
        )

    try:
        with pytest.raises(DBAPIError, match="canonical code.*골든 테스트 증거"):
            command.downgrade(config, CANONICAL_GATE_PARENT)
        with postgres_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == REPOSITORY_HEAD
            )

        with postgres_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM rule_golden_test_artifacts WHERE id = :id"),
                {"id": artifact_id},
            )
            connection.execute(
                text("UPDATE institutions SET code = 'SYNTHETIC_BLOCK' WHERE id = :id"),
                {"id": institution_id},
            )
        with pytest.raises(DBAPIError, match="canonical code.*골든 테스트 증거"):
            command.downgrade(config, CANONICAL_GATE_PARENT)

        with postgres_engine.begin() as connection:
            connection.execute(
                text("UPDATE institutions SET code = NULL WHERE id = :id"),
                {"id": institution_id},
            )
            connection.execute(
                text("UPDATE campuses SET code = 'SYNTHETIC_MAIN' WHERE id = :id"),
                {"id": campus_id},
            )
        with pytest.raises(DBAPIError, match="canonical code.*골든 테스트 증거"):
            command.downgrade(config, CANONICAL_GATE_PARENT)

        with postgres_engine.begin() as connection:
            connection.execute(
                text("UPDATE campuses SET code = NULL WHERE id = :id"),
                {"id": campus_id},
            )
        command.downgrade(config, CANONICAL_GATE_PARENT)

        downgraded_tables = set(inspect(postgres_engine).get_table_names())
        assert "rule_golden_test_artifacts" not in downgraded_tables
        assert "code" not in {
            column["name"] for column in inspect(postgres_engine).get_columns("institutions")
        }
        assert "code" not in {
            column["name"] for column in inspect(postgres_engine).get_columns("campuses")
        }
        with postgres_engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM institutions WHERE id = :id"),
                    {"id": institution_id},
                )
                == 1
            )
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM campuses WHERE id = :id"),
                    {"id": campus_id},
                )
                == 1
            )

        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO admission_eligibility_rules (
                        id, version, lifecycle_status, rule_payload,
                        independent_verified, golden_test_ref
                    ) VALUES (
                        :id, 'synthetic-legacy-ref-v1', 'DRAFT',
                        '{}'::json, FALSE, 'legacy-unverified-ref'
                    )
                    """
                ),
                {"id": legacy_rule_id},
            )
        with pytest.raises(DBAPIError, match="검증되지 않은 기존 golden_test_ref"):
            command.upgrade(config, CANONICAL_GATE_HEAD)
        with postgres_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == CANONICAL_GATE_PARENT
            )
        assert "rule_golden_test_artifacts" not in set(inspect(postgres_engine).get_table_names())
        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE admission_eligibility_rules SET golden_test_ref = NULL WHERE id = :id"
                ),
                {"id": legacy_rule_id},
            )

        command.upgrade(config, CANONICAL_GATE_HEAD)
        with postgres_engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT code FROM institutions WHERE id = :id"),
                    {"id": institution_id},
                )
                is None
            )
            assert (
                connection.scalar(
                    text("SELECT code FROM campuses WHERE id = :id"),
                    {"id": campus_id},
                )
                is None
            )
    finally:
        command.upgrade(config, REPOSITORY_HEAD)
        with postgres_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM admission_eligibility_rules WHERE id = :id"),
                {"id": legacy_rule_id},
            )
            connection.execute(
                text("DELETE FROM rule_golden_test_artifacts WHERE id = :id"),
                {"id": artifact_id},
            )
            connection.execute(
                text("DELETE FROM rule_reviews WHERE id = :id"),
                {"id": review_id},
            )
            connection.execute(
                text("DELETE FROM campuses WHERE id = :id"),
                {"id": campus_id},
            )
            connection.execute(
                text("DELETE FROM institutions WHERE id = :id"),
                {"id": institution_id},
            )


def test_tested_audit_contract_downgrade_is_fail_closed_and_null_safe(
    postgres_engine: Engine,
) -> None:
    config = Config("alembic.ini")
    review_id = str(uuid4())
    rule_id = str(uuid4())
    audit_event_id = str(uuid4())

    with postgres_engine.begin() as connection:
        _insert_rule_review(connection, review_id=review_id, rule_id=rule_id)
        connection.execute(
            text(
                """
                UPDATE rule_reviews
                SET payload_digest = :payload_digest,
                    contract_digest = :contract_digest,
                    contract_schema_version = 2
                WHERE id = :review_id
                """
            ),
            {
                "review_id": review_id,
                "payload_digest": "a" * 64,
                "contract_digest": "b" * 64,
            },
        )

    try:
        command.downgrade(config, CANONICAL_GATE_PARENT)
        with pytest.raises(DBAPIError, match="규칙 검수 계약 데이터 또는 감사 이벤트"):
            command.downgrade(config, TESTED_AUDIT_PARENT)
        with postgres_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT version_num FROM alembic_version"))
                == CANONICAL_GATE_PARENT
            )

        with postgres_engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE rule_reviews
                    SET payload_digest = NULL,
                        contract_digest = NULL,
                        contract_schema_version = NULL
                    WHERE id = :review_id
                    """
                ),
                {"review_id": review_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO rule_audit_events (
                        id, rule_type, rule_id, action, actor_ref,
                        occurred_at, details
                    ) VALUES (
                        :id, 'SCORE_RULE', :rule_id, 'EXTRACTED',
                        :actor_ref, :occurred_at, '{}'::json
                    )
                    """
                ),
                {
                    "id": audit_event_id,
                    "rule_id": rule_id,
                    "actor_ref": f"synthetic-actor-{audit_event_id}",
                    "occurred_at": datetime(2026, 7, 15, tzinfo=UTC),
                },
            )
        with pytest.raises(DBAPIError, match="규칙 검수 계약 데이터 또는 감사 이벤트"):
            command.downgrade(config, TESTED_AUDIT_PARENT)

        with postgres_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM rule_audit_events WHERE id = :id"),
                {"id": audit_event_id},
            )
        command.downgrade(config, TESTED_AUDIT_PARENT)

        downgraded_review_columns = {
            column["name"] for column in inspect(postgres_engine).get_columns("rule_reviews")
        }
        assert {
            "payload_digest",
            "contract_digest",
            "contract_schema_version",
        }.isdisjoint(downgraded_review_columns)
        with postgres_engine.connect() as connection:
            assert (
                connection.scalar(
                    text("SELECT count(*) FROM rule_reviews WHERE id = :review_id"),
                    {"review_id": review_id},
                )
                == 1
            )

        command.upgrade(config, REPOSITORY_HEAD)
        with postgres_engine.connect() as connection:
            restored_contract = connection.execute(
                text(
                    """
                    SELECT payload_digest, contract_digest, contract_schema_version
                    FROM rule_reviews
                    WHERE id = :review_id
                    """
                ),
                {"review_id": review_id},
            ).one()
            assert tuple(restored_contract) == (None, None, None)
    finally:
        command.upgrade(config, REPOSITORY_HEAD)
        with postgres_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM rule_audit_events WHERE id = :id"),
                {"id": audit_event_id},
            )
            connection.execute(
                text("DELETE FROM rule_reviews WHERE id = :id"),
                {"id": review_id},
            )


def test_flask_db_upgrade_and_migrate_commands(postgres_engine: Engine, tmp_path: Path) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": str(postgres_engine.url),
        }
    )
    runner = app.test_cli_runner()

    upgrade_result = runner.invoke(args=["db", "upgrade"])

    assert upgrade_result.exit_code == 0, upgrade_result.output

    temporary_migrations = tmp_path / "migrations"
    shutil.copytree("migrations", temporary_migrations)
    existing_revisions = set((temporary_migrations / "versions").glob("*.py"))

    migrate_result = runner.invoke(
        args=[
            "db",
            "--directory",
            str(temporary_migrations),
            "migrate",
            "--message",
            "schema drift verification",
        ]
    )

    assert migrate_result.exit_code == 0, migrate_result.output
    assert set((temporary_migrations / "versions").glob("*.py")) == existing_revisions
