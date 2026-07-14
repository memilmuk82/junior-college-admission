from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app import create_app
from app.models import (
    AdmissionRound,
    AdmissionTrack,
    Campus,
    Institution,
    Program,
    RuleAuditEvent,
    RuleGoldenTestArtifact,
    RuleReview,
    ScoreRule,
    SourceCitation,
    SourceDocument,
    SourceDocumentPage,
)
from app.services.rule_admin import (
    RULE_CONTRACT_SCHEMA_VERSION,
    GoldenTestRunEvidence,
    record_golden_test_artifact,
    rule_contract_digest,
    rule_payload_digest,
)
from app.services.score_rule_schema import (
    parse_score_rule_csv,
    score_rule_form_values,
    write_score_rule_csv,
)
from tests.test_consultations import _score_payload
from tests.test_score_rule_schema import _csv_bytes, _valid_row


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def test_authenticated_admin_can_list_and_open_rule_detail(postgres_engine: Engine) -> None:
    with Session(postgres_engine) as database_session:
        rule = ScoreRule(
            version="synthetic-admin-v1",
            lifecycle_status="DRAFT",
            rule_payload={"schema_version": 1, "synthetic": True},
        )
        database_session.add(rule)
        database_session.commit()
        rule_id = rule.id

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "ADMIN_USERNAME": "synthetic-admin",
            "ADMIN_PASSWORD_HASH": generate_password_hash("synthetic-password"),
        }
    )
    client = app.test_client()
    login_page = client.get("/admin/login")
    login = client.post(
        "/admin/login",
        data={
            "csrf_token": _csrf(login_page.get_data(as_text=True)),
            "username": "synthetic-admin",
            "password": "synthetic-password",
        },
    )
    assert login.status_code == 302

    listing = client.get("/admin/rules")
    assert listing.status_code == 200
    assert listing.headers["Cache-Control"] == "no-store, max-age=0"
    assert "synthetic-admin-v1" in listing.get_data(as_text=True)

    detail = client.get(f"/admin/rules/SCORE_RULE/{rule_id}")
    assert detail.status_code == 200
    body = detail.get_data(as_text=True)
    assert "Canonical payload" in body
    assert "synthetic-admin-v1" in body
    assert "DRAFT" in body

    with Session(postgres_engine) as database_session:
        loaded_rule = database_session.get(ScoreRule, rule_id)
        assert loaded_rule is not None
        loaded_rule.lifecycle_status = "TESTED"
        database_session.commit()

    blocked_edit = client.get(f"/admin/rules/SCORE_RULE/{rule_id}/edit")
    assert blocked_edit.status_code == 409

    with Session(postgres_engine) as database_session:
        database_session.execute(delete(ScoreRule).where(ScoreRule.id == rule_id))
        database_session.commit()


def test_admin_records_tested_state_from_a_passed_golden_artifact(
    postgres_engine: Engine,
) -> None:
    occurred_at = datetime(2026, 7, 14, tzinfo=UTC)
    with Session(postgres_engine) as database_session:
        institution = Institution(
            code="SYNTHETIC_REVIEW",
            name="합성 관리자 검수 대학",
            institution_type="JUNIOR_COLLEGE",
        )
        database_session.add(institution)
        database_session.flush()
        campus = Campus(institution_id=institution.id, code="MAIN", name="합성 검수 캠퍼스")
        database_session.add(campus)
        database_session.flush()
        program = Program(campus_id=campus.id, code="SYNTHETIC", name="합성 검수 학과")
        admission_round = AdmissionRound(
            institution_id=institution.id,
            academic_year=2027,
            code="EARLY_1",
            name="수시 1차",
        )
        database_session.add_all([program, admission_round])
        database_session.flush()
        track = AdmissionTrack(
            admission_round_id=admission_round.id,
            program_id=program.id,
            code="GENERAL",
            name="일반전형",
        )
        document = SourceDocument(
            academic_year=2027,
            institution_id=institution.id,
            campus_id=campus.id,
            document_type="FINAL_GUIDE",
            document_status="HUMAN_APPROVED",
            file_hash="7" * 64,
            page_count=3,
            detected_years=[2027],
            year_consistency_status="CONSISTENT",
            verification_status="HUMAN_APPROVED",
        )
        database_session.add_all([track, document])
        database_session.flush()
        page = SourceDocumentPage(
            source_document_id=document.id,
            page_number=2,
            detected_academic_year=2027,
            verification_status="HUMAN_APPROVED",
        )
        database_session.add(page)
        database_session.flush()
        citation = SourceCitation(
            source_document_id=document.id,
            source_document_page_id=page.id,
            page_number=2,
            locator="합성 검수 표",
        )
        database_session.add(citation)
        database_session.flush()
        rule = ScoreRule(
            admission_track_id=track.id,
            version="synthetic-tested-route-v1",
            lifecycle_status="DRAFT",
            rule_payload=_score_payload(),
            source_citation_id=citation.id,
            admission_year=2027,
            university_code="SYNTHETIC_REVIEW",
            university_name="합성 관리자 검수 대학",
            campus_code="MAIN",
            admission_round="EARLY_1",
            admission_track_code="GENERAL",
            admission_track_name="일반전형",
            evidence_document_ref=document.id,
            evidence_page=2,
            evidence_location="합성 검수 표",
            source_status="FINAL_GUIDE",
        )
        database_session.add(rule)
        database_session.flush()
        review = RuleReview(
            rule_type="SCORE_RULE",
            rule_id=rule.id,
            review_kind="INDEPENDENT_VERIFICATION",
            review_status="APPROVED",
            reviewer_ref="synthetic-second-reviewer",
            reviewed_at=occurred_at,
            payload_digest=rule_payload_digest(rule.rule_payload),
            contract_digest=rule_contract_digest(database_session, "SCORE_RULE", rule),
            contract_schema_version=RULE_CONTRACT_SCHEMA_VERSION,
        )
        database_session.add(review)
        database_session.commit()
        ids = {
            "institution": institution.id,
            "campus": campus.id,
            "program": program.id,
            "round": admission_round.id,
            "track": track.id,
            "document": document.id,
            "page": page.id,
            "citation": citation.id,
            "rule": rule.id,
            "review": review.id,
        }

    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "ADMIN_USERNAME": "synthetic-admin",
            "ADMIN_PASSWORD_HASH": generate_password_hash("synthetic-password"),
        }
    )
    client = app.test_client()
    login_page = client.get("/admin/login")
    client.post(
        "/admin/login",
        data={
            "csrf_token": _csrf(login_page.get_data(as_text=True)),
            "username": "synthetic-admin",
            "password": "synthetic-password",
        },
    )
    detail = client.get(f"/admin/rules/SCORE_RULE/{ids['rule']}")
    body = detail.get_data(as_text=True)
    assert "EXTRACTED 상태 기록" in body

    extracted = client.post(
        f"/admin/rules/SCORE_RULE/{ids['rule']}/extract",
        data={
            "csrf_token": _csrf(body),
            "confirmation": "EXTRACTED",
        },
    )
    assert extracted.status_code == 302

    detail = client.get(f"/admin/rules/SCORE_RULE/{ids['rule']}")
    body = detail.get_data(as_text=True)
    assert "VERIFIED 상태 기록" in body
    assert "synthetic-second-reviewer" in body

    verified = client.post(
        f"/admin/rules/SCORE_RULE/{ids['rule']}/verify",
        data={
            "csrf_token": _csrf(body),
            "independent_review_id": ids["review"],
            "confirmation": "VERIFIED",
        },
    )
    assert verified.status_code == 302

    artifact_executed_at = datetime.now(UTC)
    with Session(postgres_engine) as database_session:
        valid_artifact = record_golden_test_artifact(
            database_session,
            rule_type="SCORE_RULE",
            rule_id=ids["rule"],
            evidence=GoldenTestRunEvidence(
                runner_ref="synthetic-admin-route-runner",
                executed_at=artifact_executed_at,
                suite_ref="tests/golden/admin-valid-v1",
                suite_digest="8" * 64,
                independent_review_id=ids["review"],
                case_count=2,
                passed_case_count=2,
                failed_case_count=0,
            ),
        )
        future_artifact = record_golden_test_artifact(
            database_session,
            rule_type="SCORE_RULE",
            rule_id=ids["rule"],
            evidence=GoldenTestRunEvidence(
                runner_ref="synthetic-admin-route-runner",
                executed_at=artifact_executed_at + timedelta(days=1),
                suite_ref="tests/golden/admin-future-v1",
                suite_digest="9" * 64,
                independent_review_id=ids["review"],
                case_count=1,
                passed_case_count=1,
                failed_case_count=0,
            ),
        )
        failed_artifact = record_golden_test_artifact(
            database_session,
            rule_type="SCORE_RULE",
            rule_id=ids["rule"],
            evidence=GoldenTestRunEvidence(
                runner_ref="synthetic-admin-route-runner",
                executed_at=artifact_executed_at,
                suite_ref="tests/golden/admin-failed-v1",
                suite_digest="a" * 64,
                independent_review_id=ids["review"],
                case_count=1,
                passed_case_count=0,
                failed_case_count=1,
            ),
        )
        stale_artifact = record_golden_test_artifact(
            database_session,
            rule_type="SCORE_RULE",
            rule_id=ids["rule"],
            evidence=GoldenTestRunEvidence(
                runner_ref="synthetic-admin-route-runner",
                executed_at=artifact_executed_at,
                suite_ref="tests/golden/admin-stale-v1",
                suite_digest="b" * 64,
                independent_review_id=ids["review"],
                case_count=1,
                passed_case_count=1,
                failed_case_count=0,
            ),
        )
        stale_artifact.payload_digest = "c" * 64
        database_session.commit()
        valid_artifact_ref = valid_artifact.artifact_ref
        valid_artifact_id = valid_artifact.id
        valid_artifact_digest = valid_artifact.artifact_digest
        excluded_artifact_refs = (
            future_artifact.artifact_ref,
            failed_artifact.artifact_ref,
            stale_artifact.artifact_ref,
        )

    detail = client.get(f"/admin/rules/SCORE_RULE/{ids['rule']}")
    body = detail.get_data(as_text=True)
    assert "TESTED 상태 기록" in body
    assert "검증된 골든 테스트" in body
    assert "tests/golden/admin-valid-v1" in body
    assert valid_artifact_ref in body
    assert all(artifact_ref not in body for artifact_ref in excluded_artifact_refs)
    assert "tests/synthetic::case" not in body

    arbitrary = client.post(
        f"/admin/rules/SCORE_RULE/{ids['rule']}/test",
        data={
            "csrf_token": _csrf(body),
            "independent_review_id": ids["review"],
            "golden_test_ref": "golden-run/arbitrary-not-recorded",
            "confirmation": "TESTED",
        },
    )
    assert arbitrary.status_code == 400
    arbitrary_body = arbitrary.get_data(as_text=True)
    assert "PASSED 골든 테스트 artifact가 필요합니다" in arbitrary_body

    tested = client.post(
        f"/admin/rules/SCORE_RULE/{ids['rule']}/test",
        data={
            "csrf_token": _csrf(arbitrary_body),
            "independent_review_id": ids["review"],
            "golden_test_ref": valid_artifact_ref,
            "confirmation": "TESTED",
        },
    )
    assert tested.status_code == 302

    with Session(postgres_engine) as database_session:
        loaded_rule = database_session.get(ScoreRule, ids["rule"])
        assert loaded_rule is not None
        assert loaded_rule.lifecycle_status == "TESTED"
        assert loaded_rule.independent_verified is True
        assert loaded_rule.golden_test_ref == valid_artifact_ref
        audit_events = tuple(
            database_session.scalars(
                select(RuleAuditEvent)
                .where(RuleAuditEvent.rule_id == loaded_rule.id)
                .order_by(RuleAuditEvent.occurred_at, RuleAuditEvent.created_at)
            )
        )
        assert tuple(event.action for event in audit_events) == (
            "EXTRACTED",
            "VERIFIED",
            "TESTED",
        )
        tested_event = audit_events[-1]
        assert tested_event.details["golden_artifact_id"] == valid_artifact_id
        assert tested_event.details["golden_artifact_digest"] == valid_artifact_digest

        database_session.execute(
            delete(RuleAuditEvent).where(RuleAuditEvent.rule_id == ids["rule"])
        )
        database_session.execute(delete(ScoreRule).where(ScoreRule.id == ids["rule"]))
        database_session.execute(
            delete(RuleGoldenTestArtifact).where(RuleGoldenTestArtifact.rule_id == ids["rule"])
        )
        database_session.execute(delete(RuleReview).where(RuleReview.id == ids["review"]))
        database_session.execute(delete(SourceCitation).where(SourceCitation.id == ids["citation"]))
        database_session.execute(
            delete(SourceDocumentPage).where(SourceDocumentPage.id == ids["page"])
        )
        database_session.execute(delete(SourceDocument).where(SourceDocument.id == ids["document"]))
        database_session.execute(delete(AdmissionTrack).where(AdmissionTrack.id == ids["track"]))
        database_session.execute(delete(Program).where(Program.id == ids["program"]))
        database_session.execute(delete(AdmissionRound).where(AdmissionRound.id == ids["round"]))
        database_session.execute(delete(Campus).where(Campus.id == ids["campus"]))
        database_session.execute(delete(Institution).where(Institution.id == ids["institution"]))
        database_session.commit()


def test_admin_csv_preview_saves_only_confirmed_draft_and_purges_upload(
    postgres_engine: Engine, tmp_path: Path
) -> None:
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "TEMP_UPLOAD_ROOT": str(tmp_path),
            "ADMIN_USERNAME": "synthetic-admin",
            "ADMIN_PASSWORD_HASH": generate_password_hash("synthetic-password"),
        }
    )
    client = app.test_client()
    login_page = client.get("/admin/login")
    client.post(
        "/admin/login",
        data={
            "csrf_token": _csrf(login_page.get_data(as_text=True)),
            "username": "synthetic-admin",
            "password": "synthetic-password",
        },
    )
    parsed = parse_score_rule_csv(_csv_bytes([_valid_row()]))
    assert parsed.issues == ()
    upload_page = client.get("/admin/rules/csv")
    preview = client.post(
        "/admin/rules/csv",
        data={
            "csrf_token": _csrf(upload_page.get_data(as_text=True)),
            "score_rules_csv": (
                BytesIO(write_score_rule_csv(parsed.rows)),
                "score_rules.csv",
            ),
        },
        content_type="multipart/form-data",
    )
    assert preview.status_code == 200
    body = preview.get_data(as_text=True)
    assert "NEW" in body
    assert "선택 행을 DRAFT로 저장" in body
    session_match = re.search(r"/admin/rules/csv/([0-9a-f]{32})/confirm", body)
    assert session_match is not None
    review_session_id = session_match.group(1)

    confirmed = client.post(
        f"/admin/rules/csv/{review_session_id}/confirm",
        data={"csrf_token": _csrf(body), "selected_row": "2"},
    )
    assert confirmed.status_code == 302
    assert not (tmp_path / review_session_id).exists()

    exported = client.get("/admin/rules/csv/export")
    assert exported.status_code == 200
    assert exported.headers["Cache-Control"] == "no-store, max-age=0"
    assert exported.headers["Content-Disposition"] == 'attachment; filename="score_rules.csv"'
    exported_rules = parse_score_rule_csv(exported.data)
    assert exported_rules.issues == ()
    assert len(exported_rules.rows) == 1
    assert exported_rules.rows[0].identity == parsed.rows[0].identity
    assert exported_rules.rows[0].rule_version == parsed.rows[0].rule_version

    with Session(postgres_engine) as database_session:
        rule = database_session.scalar(
            select(ScoreRule).where(ScoreRule.version == parsed.rows[0].rule_version)
        )
        assert rule is not None
        rule_id = rule.id

    edit_page = client.get(f"/admin/rules/SCORE_RULE/{rule_id}/edit")
    assert edit_page.status_code == 200
    assert "DRAFT 성적 규칙 직접 편집" in edit_page.get_data(as_text=True)
    edit_values = score_rule_form_values(parsed.rows[0])
    edit_values["maximum_score"] = "900"
    edit_values["administrator_note"] = "합성 관리자 직접 편집"
    updated = client.post(
        f"/admin/rules/SCORE_RULE/{rule_id}/edit",
        data={
            **edit_values,
            "csrf_token": _csrf(edit_page.get_data(as_text=True)),
            "admission_track_id": "",
            "source_citation_id": "",
        },
    )
    assert updated.status_code == 302

    with Session(postgres_engine) as database_session:
        rule = database_session.get(ScoreRule, rule_id)
        assert rule is not None
        assert rule.lifecycle_status == "DRAFT"
        assert rule.admission_track_id is None
        assert rule.rule_payload["maximum_score"] == "900"
        assert rule.administrator_note == "합성 관리자 직접 편집"
        actions = tuple(
            database_session.scalars(
                select(RuleAuditEvent.action)
                .where(RuleAuditEvent.rule_id == rule.id)
                .order_by(RuleAuditEvent.created_at)
            )
        )
        assert actions == ("DRAFT_CREATED", "DRAFT_UPDATED")
        database_session.execute(delete(RuleAuditEvent).where(RuleAuditEvent.rule_id == rule.id))
        database_session.delete(rule)
        database_session.commit()
