from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AdmissionEligibilityRule,
    Institution,
    SourceDocument,
    StudentAcademicRecord,
)


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


def test_mixed_year_document_cannot_be_published(session: Session) -> None:
    institution = Institution(name="합성전문대", institution_type="JUNIOR_COLLEGE")
    session.add(institution)
    session.flush()
    session.add(
        SourceDocument(
            academic_year=2027,
            institution_id=institution.id,
            document_type="FINAL_GUIDE",
            document_status="PUBLISHED",
            published_at=datetime(2026, 7, 10, tzinfo=UTC),
            file_hash="a" * 64,
            page_count=2,
            detected_years=[2026, 2027],
            year_consistency_status="MIXED_YEAR",
            verification_status="HUMAN_APPROVED",
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()


def test_unapproved_rule_cannot_be_published(session: Session) -> None:
    session.add(
        AdmissionEligibilityRule(
            version="synthetic-v1",
            lifecycle_status="PUBLISHED",
            rule_payload={"all": []},
            independent_verified=False,
        )
    )

    with pytest.raises(IntegrityError):
        session.flush()


def test_home_and_vocational_records_stay_separate(session: Session) -> None:
    session.add_all(
        [
            StudentAcademicRecord(
                student_id="synthetic-student-001",
                academic_year=2027,
                grade=3,
                semester=1,
                record_source="HOME_SCHOOL_RECORD",
                verification_status="USER_VERIFIED",
            ),
            StudentAcademicRecord(
                student_id="synthetic-student-001",
                academic_year=2027,
                grade=3,
                semester=1,
                record_source="VOCATIONAL_TRAINING_RECORD",
                is_vocational_training_semester=True,
                verification_status="USER_VERIFIED",
            ),
        ]
    )
    session.flush()

    records = (
        session.query(StudentAcademicRecord).order_by(StudentAcademicRecord.record_source).all()
    )
    assert [record.record_source for record in records] == [
        "HOME_SCHOOL_RECORD",
        "VOCATIONAL_TRAINING_RECORD",
    ]
