from __future__ import annotations

import re

from werkzeug.security import generate_password_hash

from app import create_app


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _client():  # type: ignore[no-untyped-def]
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "ADMIN_USERNAME": "synthetic-admin",
            "ADMIN_PASSWORD_HASH": generate_password_hash("synthetic-password"),
        }
    )
    return app.test_client()


def test_admin_rules_require_authentication() -> None:
    response = _client().get("/admin/rules")

    assert response.status_code == 302
    assert "/admin/login" in response.headers["Location"]


def test_admin_login_requires_csrf_and_valid_hashed_password() -> None:
    client = _client()
    page = client.get("/admin/login")
    token = _csrf(page.get_data(as_text=True))

    invalid = client.post(
        "/admin/login",
        data={"csrf_token": token, "username": "synthetic-admin", "password": "wrong"},
    )
    assert invalid.status_code == 401
    assert "관리자 인증 정보를 확인하세요" in invalid.get_data(as_text=True)

    token = _csrf(invalid.get_data(as_text=True))
    valid = client.post(
        "/admin/login",
        data={
            "csrf_token": token,
            "username": "synthetic-admin",
            "password": "synthetic-password",
        },
    )
    assert valid.status_code == 302
    assert valid.headers["Location"].endswith("/admin/rules")
