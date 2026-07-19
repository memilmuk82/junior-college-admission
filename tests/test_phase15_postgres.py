from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from flask import render_template
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app import create_app
from app.models import AdmissionRound, AdmissionTrack, Campus, Institution, Program, UserAccount
from app.services.institutional_results import (
    create_outcome,
    list_outcomes,
    summarize_outcomes,
)
from app.services.membership import bootstrap_admin
from app.services.source_documents import (
    create_validation_decision,
    register_source_document,
    resolve_validation_decision,
)


def _catalog(session: Session) -> AdmissionTrack:
    institution = Institution(code="SYNTHETIC", name="합성전문대", institution_type="COLLEGE")
    session.add(institution)
    session.flush()
    campus = Campus(code="MAIN", institution_id=institution.id, name="본교")
    session.add(campus)
    session.flush()
    program = Program(campus_id=campus.id, code="CS", name="컴퓨터학과")
    round_row = AdmissionRound(
        institution_id=institution.id, academic_year=2027, code="EARLY_1", name="수시1차"
    )
    session.add_all((program, round_row))
    session.flush()
    track = AdmissionTrack(
        admission_round_id=round_row.id,
        program_id=program.id,
        code="GENERAL",
        name="일반전형",
    )
    session.add(track)
    session.flush()
    return track


def test_teacher_outcome_is_private_and_aggregates_without_personal_data(
    postgres_engine: Engine,
) -> None:
    connection = postgres_engine.connect()
    transaction = connection.begin()
    session = Session(connection)
    try:
        admin = bootstrap_admin(
            session,
            login_name="phase15-outcome-admin",
            password_hash="synthetic-password-hash",
            occurred_at=datetime.now(UTC),
        )
        teacher = UserAccount(
            actor_ref="phase15-teacher",
            login_name="phase15-teacher",
            email="phase15-teacher@example.test",
            display_name="합성 교사",
            password_hash="synthetic-password-hash",
            role="TEACHER",
            status="ACTIVE",
            approved_at=datetime.now(UTC),
            approved_by_user_id=admin.id,
        )
        session.add(teacher)
        track = _catalog(session)
        create_outcome(
            session,
            user=teacher,
            values={
                "academic_year": "2027",
                "anonymous_student_code": "C27-001",
                "admission_track_id": track.id,
                "reflected_grade": "3.25",
                "outcome_status": "WAITLIST_ACCEPTED",
                "initial_waitlist_number": "8",
                "final_waitlist_number": "3",
                "source_status": "TEACHER_CONFIRMED",
                "notes": "합성 비식별 기록",
            },
        )
        session.flush()

        rows = list_outcomes(session, user=teacher, academic_year=2027)
        summary = summarize_outcomes(rows)

        assert len(rows) == 1
        assert rows[0].outcome.anonymous_student_code == "C27-001"
        assert rows[0].track.program_name == "컴퓨터학과"
        assert summary.waitlist_accepted == 1
        app = create_app({"TESTING": True, "SECRET_KEY": "test"})
        with app.test_request_context():
            html = render_template(
                "teacher_outcomes.html",
                current_user=teacher,
                csrf_token="synthetic-csrf",
                rows=rows,
                summary=summary,
                track_options=(rows[0].track,),
                filters={
                    "academic_year": "2027",
                    "institution_id": "",
                    "program_id": "",
                    "admission_track_id": "",
                    "outcome_status": "",
                },
                error=None,
            )
        assert "기관 지원·합격 결과" in html
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def test_source_document_versions_and_validation_decision_are_separate(
    tmp_path: Path, postgres_engine: Engine
) -> None:
    connection = postgres_engine.connect()
    transaction = connection.begin()
    session = Session(connection)
    try:
        admin = bootstrap_admin(
            session,
            login_name="phase15-source-admin",
            password_hash="synthetic-password-hash",
            occurred_at=datetime.now(UTC),
        )
        document = register_source_document(
            session,
            storage_root=tmp_path,
            filename="synthetic-results.csv",
            body="대학명,학과명\n합성전문대,컴퓨터학과\n".encode(),
            academic_year="2027",
            document_type="ADMISSION_RESULT",
            institution_id="",
            admission_round_id="",
            original_url="https://example.test/results",
            announced_at="2026-07-19",
            revision_label="합성 최초본",
        )
        decision = create_validation_decision(
            session,
            source_document_id=document.id,
            entity_type="ADMISSION_RESULT",
            entity_reference="SYNTHETIC/CS",
            field_name="average_grade",
            current_value="3.2",
            portal_value="3.3",
            document_value="3.2",
        )
        session.flush()
        resolve_validation_decision(
            session,
            decision_id=decision.id,
            user=admin,
            resolution_status="CONFIRMED",
            resolved_value="3.2",
            resolution_reason="공식 문서와 현재 값이 일치함",
        )

        assert document.is_current is True
        assert document.storage_path and document.storage_path.endswith(".csv")
        assert decision.resolution_status == "CONFIRMED"
        assert decision.reviewed_by_user_account_id == admin.id
        app = create_app({"TESTING": True, "SECRET_KEY": "test"})
        with app.test_request_context():
            html = render_template(
                "admin_source_documents.html",
                csrf_token="synthetic-csrf",
                documents=(document,),
                decisions=(decision,),
                institutions=(),
                rounds=(),
                error=None,
            )
        assert "출처 문서와 검증 결정" in html
    finally:
        session.close()
        transaction.rollback()
        connection.close()
