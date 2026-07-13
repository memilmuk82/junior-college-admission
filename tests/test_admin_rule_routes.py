from __future__ import annotations

import re

from sqlalchemy import Engine, delete
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app import create_app
from app.models import ScoreRule


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
