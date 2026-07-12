from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import Engine, inspect

from app import create_app


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
        "campuses",
        "disqualification_rules",
        "document_requirements",
        "grade_source_scope_rules",
        "import_batches",
        "institutions",
        "multiple_application_rules",
        "programs",
        "rule_reviews",
        "rule_audit_events",
        "rule_version_lineages",
        "score_adjustment_rules",
        "score_rules",
        "source_citations",
        "source_document_pages",
        "source_documents",
        "student_academic_records",
        "student_course_records",
        "tie_break_rules",
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
