from __future__ import annotations

import re

from cryptography.fernet import Fernet
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app import create_app
from app.models import AiConsultationDraft, AiProviderCredential


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _client(postgres_engine: Engine, master_key: str):  # type: ignore[no-untyped-def]
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test-only-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "ADMIN_USERNAME": "synthetic-admin",
            "ADMIN_PASSWORD_HASH": generate_password_hash("synthetic-password"),
            "BYOK_MASTER_KEY": master_key,
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
    return client


def test_admin_can_store_mask_and_delete_provider_key(postgres_engine: Engine) -> None:
    client = _client(postgres_engine, Fernet.generate_key().decode("ascii"))
    page = client.get("/admin/ai/settings")

    assert page.status_code == 200
    assert page.headers["Cache-Control"] == "no-store, max-age=0"
    saved = client.post(
        "/admin/ai/credentials",
        data={
            "csrf_token": _csrf(page.get_data(as_text=True)),
            "provider": "OPENAI",
            "api_key": "synthetic-provider-key-1234",
        },
        follow_redirects=True,
    )

    body = saved.get_data(as_text=True)
    assert saved.status_code == 200
    assert "••••1234" in body
    assert "synthetic-provider-key" not in body
    with Session(postgres_engine) as database_session:
        credential = database_session.scalar(
            select(AiProviderCredential).where(
                AiProviderCredential.actor_ref == "synthetic-admin",
                AiProviderCredential.provider == "OPENAI",
            )
        )
        assert credential is not None
        assert "synthetic-provider-key" not in credential.encrypted_api_key

    deleted = client.post(
        "/admin/ai/credentials/OPENAI/delete",
        data={"csrf_token": _csrf(body)},
        follow_redirects=True,
    )
    assert deleted.status_code == 200
    assert "••••1234" not in deleted.get_data(as_text=True)
    with Session(postgres_engine) as database_session:
        assert database_session.scalar(select(AiProviderCredential)) is None


def test_admin_can_review_edit_and_confirm_only_owned_draft(postgres_engine: Engine) -> None:
    with Session(postgres_engine) as database_session:
        record = AiConsultationDraft(
            actor_ref="synthetic-admin",
            provider="ANTHROPIC",
            model_name="synthetic-model",
            payload_schema_version=1,
            payload_digest="b" * 64,
            generated_text="검증된 결과를 설명하는 합성 초안입니다.",
            check_items=["최종 자료를 확인하세요."],
            status="GENERATED_DRAFT",
        )
        database_session.add(record)
        database_session.commit()
        draft_id = record.id

    client = _client(postgres_engine, Fernet.generate_key().decode("ascii"))
    page = client.get(f"/admin/ai/drafts/{draft_id}")

    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "검증된 결과를 설명하는 합성 초안입니다." in body
    confirmed = client.post(
        f"/admin/ai/drafts/{draft_id}/confirm",
        data={
            "csrf_token": _csrf(body),
            "teacher_text": "교사가 검토하고 수정한 합성 상담 문장입니다.",
        },
        follow_redirects=True,
    )

    assert confirmed.status_code == 200
    assert "TEACHER_CONFIRMED" in confirmed.get_data(as_text=True)
    with Session(postgres_engine) as database_session:
        loaded = database_session.get(AiConsultationDraft, draft_id)
        assert loaded is not None
        assert loaded.teacher_text == "교사가 검토하고 수정한 합성 상담 문장입니다."
        assert loaded.confirmed_by == "synthetic-admin"
        assert loaded.confirmed_at is not None
        database_session.execute(
            delete(AiConsultationDraft).where(AiConsultationDraft.id == draft_id)
        )
        database_session.commit()


def test_admin_can_reject_an_unconfirmed_draft(postgres_engine: Engine) -> None:
    with Session(postgres_engine) as database_session:
        record = AiConsultationDraft(
            actor_ref="synthetic-admin",
            provider="OPENAI",
            model_name="synthetic-model",
            payload_schema_version=1,
            payload_digest="d" * 64,
            generated_text="거절할 합성 초안입니다.",
            check_items=[],
            status="GENERATED_DRAFT",
        )
        database_session.add(record)
        database_session.commit()
        draft_id = record.id

    client = _client(postgres_engine, Fernet.generate_key().decode("ascii"))
    page = client.get(f"/admin/ai/drafts/{draft_id}")
    rejected = client.post(
        f"/admin/ai/drafts/{draft_id}/reject",
        data={"csrf_token": _csrf(page.get_data(as_text=True))},
        follow_redirects=True,
    )

    assert rejected.status_code == 200
    assert "REJECTED" in rejected.get_data(as_text=True)
    with Session(postgres_engine) as database_session:
        loaded = database_session.get(AiConsultationDraft, draft_id)
        assert loaded is not None
        assert loaded.status == "REJECTED"
        assert loaded.teacher_text is None
        database_session.delete(loaded)
        database_session.commit()


def test_missing_master_key_disables_key_write_without_breaking_settings(
    postgres_engine: Engine,
) -> None:
    client = _client(postgres_engine, "")
    page = client.get("/admin/ai/settings")

    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "키 암호화 설정이 없어" in body
    blocked = client.post(
        "/admin/ai/credentials",
        data={
            "csrf_token": _csrf(body),
            "provider": "OPENAI",
            "api_key": "synthetic-provider-key-1234",
        },
    )
    assert blocked.status_code == 503
