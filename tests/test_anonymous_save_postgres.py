from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app.models import (
    SavedConsultation,
    StudentAcademicRecord,
    StudentCourseRecord,
    UserAccount,
    UserAccountAuditEvent,
)
from app.services.anonymous_calculations import (
    AnonymousCalculationState,
    save_anonymous_consultation,
    save_anonymous_records,
)
from app.services.membership import bootstrap_admin
from app.services.structured_imports import NormalizedCourseRow


def _state(rank_grade: str) -> AnonymousCalculationState:
    now = datetime.now(UTC)
    return AnonymousCalculationState(
        owner_token="synthetic-owner-token",
        created_at=now,
        expires_at=now + timedelta(minutes=30),
        record_source="HOME_SCHOOL_RECORD",
        is_vocational_training_semester=False,
        rows=(
            NormalizedCourseRow(
                academic_year=2026,
                grade=1,
                semester=1,
                subject_group="국어",
                subject_name="합성 국어",
                credits=Decimal("4"),
                raw_score=None,
                course_mean=None,
                standard_deviation=None,
                achievement_level=None,
                enrollment_count=None,
                rank_grade=Decimal(rank_grade),
                source_sheet=None,
                source_row_number=2,
                source_page=None,
                record_source="HOME_SCHOOL_RECORD",
                is_vocational_training_semester=False,
            ),
        ),
        consultation_snapshot={
            "academic_year": 2027,
            "selected_targets": [
                {
                    "program_id": "synthetic-program",
                    "institution_name": "합성 공개대학",
                    "campus_name": "본교",
                    "program_name": "합성학과",
                }
            ],
            "result_snapshot": {
                "schema_version": 2,
                "academic_year": 2027,
                "results": [
                    {
                        "item_status": "READY",
                        "target": {
                            "academic_year": 2027,
                            "institution_name": "합성 공개대학",
                            "campus_name": "본교",
                            "program_name": "합성학과",
                            "admission_round_name": "수시 1차",
                            "admission_track_name": "일반전형",
                        },
                        "eligibility": None,
                        "average_grade": None,
                        "admission_result": {"status": "NOT_AVAILABLE"},
                        "evidence": [],
                        "warnings": [],
                    }
                ],
            },
        },
    )


def test_student_resave_replaces_only_same_owned_term(postgres_engine: Engine) -> None:
    with Session(postgres_engine) as database_session:
        admin = bootstrap_admin(
            database_session,
            login_name="phase14-save-admin",
            password_hash="synthetic-password-hash",
            occurred_at=datetime.now(UTC),
        )
        student = UserAccount(
            actor_ref="user:phase14-save-student",
            login_name="phase14-save-student",
            email="student-save@phase14.invalid",
            display_name="합성 저장 학생",
            password_hash="synthetic-password-hash",
            role="STUDENT",
            status="ACTIVE",
            auth_version=1,
            approved_at=datetime.now(UTC),
            approved_by_user_id=admin.id,
        )
        database_session.add(student)
        database_session.flush()

        first_ids = save_anonymous_records(
            database_session,
            state=_state("2"),
            calculation_id="first-calculation",
            user=student,
        )
        saved_consultation = save_anonymous_consultation(
            database_session,
            state=_state("2"),
            calculation_id="first-calculation",
            user=student,
        )
        database_session.commit()

        second_ids = save_anonymous_records(
            database_session,
            state=_state("7"),
            calculation_id="second-calculation",
            user=student,
        )
        database_session.commit()

        records = tuple(
            database_session.scalars(
                select(StudentAcademicRecord).where(
                    StudentAcademicRecord.owner_user_account_id == student.id
                )
            )
        )
        courses = tuple(
            database_session.scalars(
                select(StudentCourseRecord).where(
                    StudentCourseRecord.academic_record_id == records[0].id
                )
            )
        )
        assert first_ids == second_ids
        assert len(records) == 1
        assert len(courses) == 1
        assert courses[0].rank_grade == Decimal("7")
        assert saved_consultation.owner_user_account_id == student.id
        assert saved_consultation.selected_targets[0]["program_id"] == "synthetic-program"
        assert saved_consultation.student_print_snapshot["audience"] == "STUDENT"

        database_session.execute(
            delete(StudentCourseRecord).where(
                StudentCourseRecord.academic_record_id == records[0].id
            )
        )
        database_session.execute(
            delete(SavedConsultation).where(SavedConsultation.owner_user_account_id == student.id)
        )
        database_session.delete(records[0])
        database_session.execute(
            delete(UserAccountAuditEvent).where(
                (UserAccountAuditEvent.target_user_id.in_((student.id, admin.id)))
                | (UserAccountAuditEvent.actor_user_id.in_((student.id, admin.id)))
            )
        )
        database_session.execute(delete(UserAccount).where(UserAccount.id == student.id))
        database_session.execute(delete(UserAccount).where(UserAccount.id == admin.id))
        database_session.commit()
