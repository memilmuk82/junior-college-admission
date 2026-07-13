from __future__ import annotations

import re
from io import BytesIO
from pathlib import Path

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app import create_app
from app.models import RuleAuditEvent, ScoreRule
from app.services.score_rule_schema import parse_score_rule_csv, write_score_rule_csv
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
        database_session.execute(delete(ScoreRule).where(ScoreRule.id == rule_id))
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

    with Session(postgres_engine) as database_session:
        rule = database_session.scalar(
            select(ScoreRule).where(ScoreRule.version == parsed.rows[0].rule_version)
        )
        assert rule is not None
        assert rule.lifecycle_status == "DRAFT"
        assert rule.admission_track_id is None
        database_session.execute(delete(RuleAuditEvent).where(RuleAuditEvent.rule_id == rule.id))
        database_session.delete(rule)
        database_session.commit()
