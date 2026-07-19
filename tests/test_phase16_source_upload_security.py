from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from flask.testing import FlaskClient
from PIL import Image
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash
from werkzeug.wrappers import Response

from app import create_app
from app.models import UserAccount
from app.services.membership import (
    approve_pending_member,
    bootstrap_admin,
    change_member_role,
    register_local_member,
)
from app.services.source_documents import SourceDocumentError, register_source_document

_PREFIX = "phase16-source-upload-"
_PASSWORD = "phase16-source-upload-password"
_ADMIN_LOGIN = f"{_PREFIX}admin"


def _cleanup(postgres_engine: Engine) -> None:
    with postgres_engine.begin() as connection:
        accounts = f"SELECT id FROM user_accounts WHERE login_name LIKE '{_PREFIX}%'"
        connection.execute(
            text(
                "DELETE FROM user_account_audit_events "
                f"WHERE target_user_id IN ({accounts}) OR actor_user_id IN ({accounts})"
            )
        )
        connection.execute(text(f"DELETE FROM user_accounts WHERE login_name LIKE '{_PREFIX}%'"))
        connection.execute(
            text("DELETE FROM source_documents WHERE original_filename LIKE :prefix"),
            {"prefix": f"{_PREFIX}%"},
        )


@pytest.fixture(autouse=True)
def _clean_source_upload_data(postgres_engine: Engine) -> Iterator[None]:
    _cleanup(postgres_engine)
    yield
    _cleanup(postgres_engine)


@pytest.fixture
def role_accounts(postgres_engine: Engine) -> dict[str, UserAccount]:
    with Session(postgres_engine) as session:
        admin = bootstrap_admin(
            session,
            login_name=_ADMIN_LOGIN,
            password_hash=generate_password_hash(_PASSWORD),
            occurred_at=datetime(2026, 7, 20, 9, 0, tzinfo=UTC),
        )
        assistant = register_local_member(
            session,
            login_name=f"{_PREFIX}assistant",
            email=f"{_PREFIX}assistant@example.invalid",
            display_name="합성 보조 관리자",
            password=_PASSWORD,
            requested_role="STUDENT",
            occurred_at=datetime(2026, 7, 20, 9, 1, tzinfo=UTC),
        )
        approve_pending_member(
            session,
            actor=admin,
            target=assistant,
            occurred_at=datetime(2026, 7, 20, 9, 2, tzinfo=UTC),
        )
        change_member_role(
            session,
            actor=admin,
            target=assistant,
            new_role="ASSISTANT_ADMIN",
            occurred_at=datetime(2026, 7, 20, 9, 3, tzinfo=UTC),
        )
        session.commit()
        for account in (admin, assistant):
            session.refresh(account)
            session.expunge(account)
    return {"ADMIN": admin, "ASSISTANT_ADMIN": assistant}


@pytest.fixture
def app_client(postgres_engine: Engine, tmp_path) -> FlaskClient:  # type: ignore[no-untyped-def]
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "phase16-source-upload-test-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "ADMIN_USERNAME": _ADMIN_LOGIN,
            "ADMIN_PASSWORD_HASH": generate_password_hash(_PASSWORD),
            "ALLOW_LEGACY_ADMIN_LOGIN": False,
            "GOOGLE_OIDC_ENABLED": False,
            "TEMP_UPLOAD_ROOT": str(tmp_path / "uploads"),
        }
    )
    return app.test_client()


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _login(client: FlaskClient, login_name: str) -> Response:
    login_page = client.get("/auth/login")
    return client.post(
        "/auth/login",
        data={
            "csrf_token": _csrf(login_page.get_data(as_text=True)),
            "username": login_name,
            "password": _PASSWORD,
        },
    )


def _upload_data(filename: str, payload: bytes, csrf: str) -> dict[str, object]:
    return {
        "csrf_token": csrf,
        "academic_year": "2027",
        "document_type": "ADMISSION_GUIDE",
        "institution_id": "",
        "admission_round_id": "",
        "announced_at": "",
        "revision_label": "합성 보안 검증",
        "original_url": "",
        "source_file": (BytesIO(payload), filename),
    }


def _malformed_ooxml_xlsx() -> bytes:
    output = BytesIO()
    with ZipFile(output, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            b'<?xml version="1.0" encoding="UTF-8"?><Types><Override>',
        )
    return output.getvalue()


@pytest.mark.parametrize(
    ("filename", "body"),
    (
        (f"{_PREFIX}broken.pdf", b"%PDF-not-a-real-pdf"),
        (f"{_PREFIX}broken.xlsx", b"PK\x03\x04not-a-real-xlsx"),
        (f"{_PREFIX}malformed-ooxml.xlsx", _malformed_ooxml_xlsx()),
    ),
)
def test_corrupted_pdf_and_xlsx_become_domain_errors_and_http_400(
    app_client: FlaskClient,
    role_accounts: dict[str, UserAccount],
    postgres_engine: Engine,
    tmp_path: Path,
    filename: str,
    body: bytes,
) -> None:
    with Session(postgres_engine) as session:
        with pytest.raises(SourceDocumentError, match="내용이 확장자와 일치하지 않습니다"):
            register_source_document(
                session,
                storage_root=tmp_path / "direct-service-uploads",
                filename=filename,
                body=body,
                academic_year="2027",
                document_type="ADMISSION_GUIDE",
                institution_id="",
                admission_round_id="",
                original_url="",
                announced_at="",
                revision_label="합성 보안 검증",
            )

    assert _login(app_client, role_accounts["ADMIN"].login_name or "").status_code == 302
    index = app_client.get("/admin/sources")
    upload = app_client.post(
        "/admin/sources/upload",
        data=_upload_data(filename, body, _csrf(index.get_data(as_text=True))),
        content_type="multipart/form-data",
    )

    assert upload.status_code == 400
    assert "출처 파일 내용이 확장자와 일치하지 않습니다." in upload.get_data(as_text=True)


def test_admin_can_upload_a_valid_tiny_synthetic_png(
    app_client: FlaskClient,
    role_accounts: dict[str, UserAccount],
) -> None:
    image_bytes = BytesIO()
    Image.new("RGB", (1, 1), color=(12, 34, 56)).save(image_bytes, format="PNG")
    filename = f"{_PREFIX}tiny.png"

    assert _login(app_client, role_accounts["ADMIN"].login_name or "").status_code == 302
    index = app_client.get("/admin/sources")
    upload = app_client.post(
        "/admin/sources/upload",
        data=_upload_data(filename, image_bytes.getvalue(), _csrf(index.get_data(as_text=True))),
        content_type="multipart/form-data",
    )

    assert upload.status_code == 302
    assert upload.headers["Location"].endswith("/admin/sources")
    listed = app_client.get("/admin/sources")
    assert filename in listed.get_data(as_text=True)


def test_assistant_admin_cannot_open_or_upload_source_documents(
    app_client: FlaskClient,
    role_accounts: dict[str, UserAccount],
) -> None:
    assert _login(app_client, role_accounts["ASSISTANT_ADMIN"].login_name or "").status_code == 302

    page = app_client.get("/admin/sources")
    upload = app_client.post(
        "/admin/sources/upload",
        data=_upload_data(f"{_PREFIX}blocked.png", b"not-reached", "invalid-csrf"),
        content_type="multipart/form-data",
    )

    assert page.status_code == 403
    assert upload.status_code == 403
