from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash
from werkzeug.test import TestResponse

from app import create_app
from app.models import (
    AdmissionEligibilityRule,
    AdmissionRound,
    AdmissionTrack,
    Campus,
    DisqualificationRule,
    GradeSourceScopeRule,
    Institution,
    MultipleApplicationRule,
    Program,
    RuleAuditEvent,
    RuleGoldenTestArtifact,
    RuleReview,
    ScoreRule,
    SourceCitation,
    SourceDocument,
    SourceDocumentPage,
    UserAccount,
)
from app.services.consultations import list_consultation_targets
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


def _phase12_admin_client(postgres_engine: Engine):  # type: ignore[no-untyped-def]
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "ADMIN_USERNAME": "synthetic-admin",
            "ADMIN_PASSWORD_HASH": generate_password_hash("synthetic-password"),
            "ALLOW_LEGACY_ADMIN_LOGIN": True,
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
    return app, client


def _delete_phase12_institutions(postgres_engine: Engine, *codes: str) -> None:
    with Session(postgres_engine) as database_session:
        database_session.execute(delete(Institution).where(Institution.code.in_(codes)))
        database_session.commit()


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


def _catalog_post(
    client: FlaskClient,
    path: str,
    data: dict[str, str],
    *,
    follow_redirects: bool = False,
) -> TestResponse:
    page = client.get("/admin/catalog")
    assert page.status_code == 200
    return client.post(
        path,
        data={"csrf_token": _csrf(page.get_data(as_text=True)), **data},
        follow_redirects=follow_redirects,
    )


def _catalog_case(
    kind: str,
    ids: dict[str, str],
    prefix: str,
) -> tuple[str, dict[str, str], type, dict[str, object], str]:
    if kind == "institution":
        return (
            "/admin/catalog/institutions",
            {
                "code": prefix.lower(),
                "name": f"합성 {prefix} 대학",
                "institution_type": "JUNIOR_COLLEGE",
            },
            Institution,
            {"code": prefix},
            f"합성 {prefix} 대학",
        )
    if kind == "campus":
        code = f"MAIN_{prefix}"
        return (
            "/admin/catalog/campuses",
            {
                "institution_id": ids["institution"],
                "code": code,
                "name": f"합성 {prefix} 캠퍼스",
            },
            Campus,
            {"institution_id": ids["institution"], "code": code},
            f"합성 {prefix} 캠퍼스",
        )
    if kind == "program":
        code = f"PROGRAM_{prefix}"
        return (
            "/admin/catalog/programs",
            {
                "campus_id": ids["campus"],
                "code": code,
                "name": f"합성 {prefix} 학과",
            },
            Program,
            {"campus_id": ids["campus"], "code": code},
            f"합성 {prefix} 학과",
        )
    if kind == "round":
        code = f"EARLY_{prefix}"
        return (
            "/admin/catalog/admission-rounds",
            {
                "institution_id": ids["institution"],
                "academic_year": "2027",
                "code": code,
                "name": f"합성 {prefix} 모집시기",
            },
            AdmissionRound,
            {
                "institution_id": ids["institution"],
                "academic_year": 2027,
                "code": code,
            },
            f"합성 {prefix} 모집시기",
        )
    if kind == "track":
        code = f"GENERAL_{prefix}"
        return (
            "/admin/catalog/admission-tracks",
            {
                "admission_round_id": ids["round"],
                "program_id": ids["program"],
                "code": code,
                "name": f"합성 {prefix} 일반전형",
            },
            AdmissionTrack,
            {
                "admission_round_id": ids["round"],
                "program_id": ids["program"],
                "code": code,
            },
            f"합성 {prefix} 일반전형",
        )
    raise AssertionError(f"알 수 없는 합성 기준정보 유형: {kind}")


def _catalog_id(
    postgres_engine: Engine,
    model: type,
    filters: dict[str, object],
) -> str:
    with Session(postgres_engine) as database_session:
        record_id = database_session.scalar(
            select(model.id).filter_by(**filters)  # type: ignore[attr-defined]
        )
    assert isinstance(record_id, str)
    return record_id


def _seed_catalog_via_routes(
    postgres_engine: Engine,
    client: FlaskClient,
    prefix: str,
) -> tuple[dict[str, str], str]:
    ids: dict[str, str] = {}
    body = ""
    for kind in ("institution", "campus", "program", "round", "track"):
        path, data, model, filters, expected_name = _catalog_case(kind, ids, prefix)
        response = _catalog_post(client, path, data, follow_redirects=True)
        body = response.get_data(as_text=True)
        assert response.status_code == 200
        assert expected_name in body
        ids[kind] = _catalog_id(postgres_engine, model, filters)
    return ids, body


def _assert_database_details_hidden(body: str) -> None:
    for forbidden in ("IntegrityError", "psycopg", "uq_", "INSERT INTO", "[SQL:"):
        assert forbidden not in body


def _assert_catalog_did_not_publish(session: Session, track_id: str) -> None:
    counts = tuple(
        session.scalar(select(func.count(model.id)).where(model.admission_track_id == track_id))
        for model in (
            AdmissionEligibilityRule,
            GradeSourceScopeRule,
            ScoreRule,
            MultipleApplicationRule,
            DisqualificationRule,
        )
    )
    assert counts == (0, 0, 0, 0, 0)
    assert track_id not in {
        target.admission_track_id for target in list_consultation_targets(session)
    }


def _add_active_account(
    session: Session,
    *,
    account_id: str,
    role: str,
    approved_by_user_id: str,
    prefix: str,
) -> None:
    session.add(
        UserAccount(
            id=account_id,
            actor_ref=f"user:{account_id}",
            email=f"{prefix}-{role.lower()}-{account_id[:6]}@phase12.invalid",
            display_name=f"합성 Phase 12 {role}",
            role=role,
            status="ACTIVE",
            auth_version=1,
            approved_by_user_id=approved_by_user_id,
            approved_at=datetime.now(UTC),
        )
    )
    session.flush()


def test_admin_registers_catalog_in_order_without_publishing_rules(
    postgres_engine: Engine,
) -> None:
    prefix = f"P12{uuid4().hex[:10].upper()}"
    _, client = _phase12_admin_client(postgres_engine)
    try:
        page = client.get("/admin/catalog")
        body = page.get_data(as_text=True)
        assert page.status_code == 200
        assert page.headers["Cache-Control"] == "no-store, max-age=0"
        for action in (
            "/admin/catalog/institutions",
            "/admin/catalog/campuses",
            "/admin/catalog/programs",
            "/admin/catalog/admission-rounds",
            "/admin/catalog/admission-tracks",
        ):
            assert f'action="{action}"' in body
        assert '<form method="post"' in body
        assert "<script" not in body.lower()
        assert 'href="/admin/rules"' in body
        assert 'href="/admin/consultations/new"' in body

        ids, registered_body = _seed_catalog_via_routes(postgres_engine, client, prefix)
        for kind in ("institution", "campus", "program", "round", "track"):
            code = _catalog_case(kind, ids, prefix)[1]["code"].upper()
            assert code in registered_body
        assert 'href="/admin/catalog"' in client.get("/admin/rules").get_data(as_text=True)

        with Session(postgres_engine) as database_session:
            track = database_session.get(AdmissionTrack, ids["track"])
            assert track is not None
            assert track.admission_round_id == ids["round"]
            assert track.program_id == ids["program"]
            _assert_catalog_did_not_publish(database_session, track.id)
    finally:
        _delete_phase12_institutions(postgres_engine, prefix)


def test_catalog_validation_and_duplicates_are_friendly_and_recover(
    postgres_engine: Engine,
) -> None:
    prefix = f"P12{uuid4().hex[:10].upper()}"
    _, client = _phase12_admin_client(postgres_engine)
    try:
        ids, _ = _seed_catalog_via_routes(postgres_engine, client, prefix)
        for kind, label in (
            ("institution", "대학 코드"),
            ("campus", "캠퍼스 코드"),
            ("program", "학과 코드"),
            ("round", "모집시기 코드"),
            ("track", "전형 코드"),
        ):
            path, data, *_ = _catalog_case(kind, ids, prefix)
            data["code"] = ""
            response = _catalog_post(client, path, data)
            assert response.status_code == 400
            assert label in response.get_data(as_text=True)

        path, invalid_data, *_ = _catalog_case("institution", ids, prefix)
        invalid_data |= {"code": "INVALID CODE;SELECT", "name": "합성 잘못된 코드 대학"}
        invalid = _catalog_post(client, path, invalid_data)
        assert invalid.status_code == 400
        assert "영문 대문자, 숫자, 밑줄, 하이픈" in invalid.get_data(as_text=True)

        for index, non_ascii_code in enumerate(("ß", "ı", "ſ"), start=1):
            path, invalid_data, *_ = _catalog_case("institution", ids, prefix)
            invalid_data |= {
                "code": f"{prefix}{non_ascii_code}",
                "name": f"합성 {prefix} 비ASCII 대학 {index}",
            }
            invalid = _catalog_post(client, path, invalid_data)
            assert invalid.status_code == 400
            assert "영문 대문자, 숫자, 밑줄, 하이픈" in invalid.get_data(as_text=True)

        for kind in ("institution", "track"):
            path, duplicate_data, *_ = _catalog_case(kind, ids, prefix)
            duplicate = _catalog_post(client, path, duplicate_data)
            duplicate_body = duplicate.get_data(as_text=True)
            assert duplicate.status_code == 409
            assert "이미 등록" in duplicate_body
            _assert_database_details_hidden(duplicate_body)

        path, recovery_data, *_ = _catalog_case("campus", ids, prefix)
        recovery_data |= {
            "code": f"RECOVERY_{prefix}",
            "name": f"합성 {prefix} 복구 캠퍼스",
        }
        assert _catalog_post(client, path, recovery_data).status_code == 302
    finally:
        _delete_phase12_institutions(
            postgres_engine,
            prefix,
            f"{prefix}SS",
            f"{prefix}I",
            f"{prefix}S",
        )


def test_catalog_rejects_missing_parents_and_cross_institution_track(
    postgres_engine: Engine,
) -> None:
    prefix = f"P12{uuid4().hex[:10].upper()}"
    second_code = f"SECOND_{prefix}"
    _, client = _phase12_admin_client(postgres_engine)
    try:
        ids, _ = _seed_catalog_via_routes(postgres_engine, client, prefix)
        with Session(postgres_engine) as database_session:
            second = Institution(
                code=second_code,
                name=f"합성 {prefix} 둘째 대학",
                institution_type="JUNIOR_COLLEGE",
            )
            database_session.add(second)
            database_session.flush()
            campus = Campus(
                institution_id=second.id,
                code=f"SECOND_MAIN_{prefix}",
                name=f"합성 {prefix} 둘째 캠퍼스",
            )
            database_session.add(campus)
            database_session.flush()
            program = Program(
                campus_id=campus.id,
                code=f"SECOND_PROGRAM_{prefix}",
                name=f"합성 {prefix} 둘째 학과",
            )
            database_session.add(program)
            database_session.commit()
            second_program_id = program.id

        missing_id = str(uuid4())
        for kind, parent_field, message in (
            ("campus", "institution_id", "대학 정보를 찾을 수 없습니다"),
            ("program", "campus_id", "캠퍼스 정보를 찾을 수 없습니다"),
            ("round", "institution_id", "대학 정보를 찾을 수 없습니다"),
            ("track", "admission_round_id", "모집시기 정보를 찾을 수 없습니다"),
            ("track", "program_id", "학과 정보를 찾을 수 없습니다"),
        ):
            path, data, *_ = _catalog_case(kind, ids, prefix)
            data[parent_field] = missing_id
            response = _catalog_post(client, path, data)
            body = response.get_data(as_text=True)
            assert response.status_code == 400
            assert message in body
            _assert_database_details_hidden(body)

        path, cross_data, *_ = _catalog_case("track", ids, prefix)
        cross_data |= {
            "program_id": second_program_id,
            "code": f"CROSS_{prefix}",
            "name": f"합성 {prefix} 대학 불일치 전형",
        }
        mismatched = _catalog_post(client, path, cross_data)
        assert mismatched.status_code == 400
        assert "같은 대학에 속해야 합니다" in mismatched.get_data(as_text=True)
        with Session(postgres_engine) as database_session:
            assert (
                database_session.scalar(
                    select(func.count(AdmissionTrack.id)).where(
                        AdmissionTrack.code == cross_data["code"]
                    )
                )
                == 0
            )
    finally:
        _delete_phase12_institutions(postgres_engine, prefix, second_code)


def test_catalog_requires_admin_and_csrf(postgres_engine: Engine) -> None:
    prefix = f"p12{uuid4().hex[:10]}"
    app, _ = _phase12_admin_client(postgres_engine)
    anonymous = app.test_client()
    assert anonymous.get("/admin/catalog").status_code == 302
    assert anonymous.post("/admin/catalog/institutions").status_code == 302

    admin_id, member_id, assistant_id = (str(uuid4()) for _ in range(3))
    with Session(postgres_engine) as database_session:
        _add_active_account(
            database_session,
            account_id=admin_id,
            role="ADMIN",
            approved_by_user_id=admin_id,
            prefix=prefix,
        )
        for account_id, role in (
            (member_id, "MEMBER"),
            (assistant_id, "ASSISTANT_ADMIN"),
        ):
            _add_active_account(
                database_session,
                account_id=account_id,
                role=role,
                approved_by_user_id=admin_id,
                prefix=prefix,
            )
        database_session.commit()

    try:
        for account_id in (member_id, assistant_id):
            restricted = app.test_client()
            with restricted.session_transaction() as browser_session:
                browser_session |= {"user_id": account_id, "auth_version": 1}
            assert restricted.get("/admin/catalog").status_code == 403
            assert restricted.post("/admin/catalog/institutions").status_code == 403

        administrator = app.test_client()
        with administrator.session_transaction() as browser_session:
            browser_session |= {"user_id": admin_id, "auth_version": 1}
        assert administrator.get("/admin/catalog").status_code == 200
        assert 'href="/admin/catalog"' in administrator.get("/dashboard").get_data(as_text=True)
        path, data, *_ = _catalog_case("institution", {}, prefix.upper())
        assert administrator.post(path, data=data).status_code == 400
        with Session(postgres_engine) as database_session:
            assert (
                database_session.scalar(
                    select(func.count(Institution.id)).where(Institution.code == prefix.upper())
                )
                == 0
            )
    finally:
        with Session(postgres_engine) as database_session:
            database_session.execute(
                delete(UserAccount).where(UserAccount.id.in_((member_id, assistant_id)))
            )
            database_session.execute(delete(UserAccount).where(UserAccount.id == admin_id))
            database_session.commit()


def test_catalog_hides_unexpected_database_errors_and_rolls_back(
    postgres_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    prefix = f"P12{uuid4().hex[:10].upper()}"
    _, client = _phase12_admin_client(postgres_engine)
    catalog_page = client.get("/admin/catalog")
    csrf_value = _csrf(catalog_page.get_data(as_text=True))

    def fail_with_database_error(database_session: Session, _form: object) -> None:
        database_session.execute(text("SELECT * FROM phase12_missing_catalog_table"))

    def reject_followup_catalog_query(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("DB 오류 응답을 만들면서 기준정보를 다시 조회했습니다.")

    try:
        with monkeypatch.context() as patch:
            import app.admin_routes as admin_routes

            patch.setattr(admin_routes, "create_institution", fail_with_database_error)
            patch.setattr(Session, "scalars", reject_followup_catalog_query)
            with caplog.at_level("WARNING"):
                path, data, *_ = _catalog_case("institution", {}, prefix)
                failed = client.post(path, data={"csrf_token": csrf_value, **data})
        assert failed.status_code == 503
        body = failed.get_data(as_text=True)
        assert "잠시 후 다시 시도하세요" in body
        for forbidden in (
            "phase12_missing_catalog_table",
            f"합성 {prefix} 대학",
            "SELECT *",
            "psycopg",
            "[SQL:",
        ):
            assert forbidden not in body
            assert all(forbidden not in record.getMessage() for record in caplog.records)

        path, data, *_ = _catalog_case("institution", {}, prefix)
        assert _catalog_post(client, path, data).status_code == 302
        with Session(postgres_engine) as database_session:
            assert (
                database_session.scalar(
                    select(func.count(Institution.id)).where(Institution.code == prefix)
                )
                == 1
            )
    finally:
        _delete_phase12_institutions(postgres_engine, prefix)
