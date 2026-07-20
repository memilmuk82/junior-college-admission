from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from flask.testing import FlaskClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash
from werkzeug.wrappers import Response

from app import create_app
from app.models import AiProviderCredential, UserAccount
from app.services.membership import (
    approve_pending_member,
    bootstrap_admin,
    change_member_role,
    register_local_member,
)

ACCOUNT_PREFIX = "phase16-workspace-"
ADMIN_LOGIN = f"{ACCOUNT_PREFIX}admin"
PASSWORD = "phase16-workspace-password"


def _cleanup_accounts(postgres_engine: Engine) -> None:
    with postgres_engine.begin() as connection:
        account_filter = f"SELECT id FROM user_accounts WHERE login_name LIKE '{ACCOUNT_PREFIX}%'"
        actor_filter = (
            f"SELECT actor_ref FROM user_accounts WHERE login_name LIKE '{ACCOUNT_PREFIX}%'"
        )
        connection.execute(
            text(f"DELETE FROM ai_provider_credentials WHERE actor_ref IN ({actor_filter})")
        )
        connection.execute(
            text(
                "DELETE FROM user_account_audit_events "
                f"WHERE target_user_id IN ({account_filter}) "
                f"OR actor_user_id IN ({account_filter})"
            )
        )
        connection.execute(
            text(f"DELETE FROM user_accounts WHERE login_name LIKE '{ACCOUNT_PREFIX}%'")
        )


@pytest.fixture(autouse=True)
def clean_phase16_workspace_accounts(postgres_engine: Engine) -> Iterator[None]:
    _cleanup_accounts(postgres_engine)
    yield
    _cleanup_accounts(postgres_engine)


@pytest.fixture
def role_accounts(postgres_engine: Engine) -> dict[str, UserAccount]:
    with Session(postgres_engine) as database_session:
        admin = bootstrap_admin(
            database_session,
            login_name=ADMIN_LOGIN,
            password_hash=generate_password_hash(PASSWORD),
            occurred_at=datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        )
        accounts: dict[str, UserAccount] = {"ADMIN": admin}
        for offset, role in enumerate(("STUDENT", "TEACHER", "ASSISTANT_ADMIN"), start=1):
            account = register_local_member(
                database_session,
                login_name=f"{ACCOUNT_PREFIX}{role.lower()}",
                email=f"{ACCOUNT_PREFIX}{role.lower()}@example.invalid",
                display_name=f"합성 {role} 작업공간 계정",
                password=PASSWORD,
                requested_role=role,
                occurred_at=datetime(2026, 7, 19, 12, offset, tzinfo=UTC),
            )
            approve_pending_member(
                database_session,
                actor=admin,
                target=account,
                occurred_at=datetime(2026, 7, 19, 12, offset + 10, tzinfo=UTC),
            )
            if role == "ASSISTANT_ADMIN":
                change_member_role(
                    database_session,
                    actor=admin,
                    target=account,
                    new_role=role,
                    occurred_at=datetime(2026, 7, 19, 12, offset + 20, tzinfo=UTC),
                )
            accounts[role] = account
        accounts["PENDING_MEMBER"] = register_local_member(
            database_session,
            login_name=f"{ACCOUNT_PREFIX}pending",
            email=f"{ACCOUNT_PREFIX}pending@example.invalid",
            display_name="합성 승인 대기 계정",
            password=PASSWORD,
            occurred_at=datetime(2026, 7, 19, 12, 30, tzinfo=UTC),
        )
        database_session.commit()
        for account in accounts.values():
            database_session.refresh(account)
            database_session.expunge(account)
        return accounts


@pytest.fixture
def app_client(postgres_engine: Engine, tmp_path) -> FlaskClient:  # type: ignore[no-untyped-def]
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "phase16-workspace-test-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "ADMIN_USERNAME": ADMIN_LOGIN,
            "ADMIN_PASSWORD_HASH": generate_password_hash(PASSWORD),
            "ALLOW_LEGACY_ADMIN_LOGIN": False,
            "GOOGLE_OIDC_ENABLED": False,
            "TEMP_UPLOAD_ROOT": str(tmp_path / "uploads"),
            "BYOK_MASTER_KEY": Fernet.generate_key().decode("ascii"),
        }
    )
    return app.test_client()


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _login(client: FlaskClient, login_name: str) -> Response:
    page = client.get("/auth/login")
    return client.post(
        "/auth/login",
        data={
            "csrf_token": _csrf(page.get_data(as_text=True)),
            "username": login_name,
            "password": PASSWORD,
        },
    )


@pytest.mark.parametrize(
    ("role", "expected_links", "expected_labels", "forbidden_links"),
    (
        (
            "STUDENT",
            ("/account/records", "/admin/ai/settings"),
            ("내 성적·상담 자료", "내 BYOK 분석"),
            (
                "/teacher/classrooms",
                "/admin/members",
                "/admin/admission-results",
                "/admin/sources",
            ),
        ),
        (
            "TEACHER",
            ("/teacher/classrooms", "/admin/ai/settings"),
            ("학과·학급 학생 관리", "학생 상담자료 만들기", "BYOK AI 설정"),
            ("/admin/members", "/admin/admission-results", "/admin/sources"),
        ),
        (
            "ASSISTANT_ADMIN",
            ("/admin/members",),
            ("계정 승인 요청",),
            (
                "/account/records",
                "/teacher/classrooms",
                "/admin/consultations/new",
                "/admin/ai/settings",
                "/teacher/outcomes",
                "/admin/admission-results",
                "/admin/sources",
            ),
        ),
    ),
)
def test_dashboard_shows_only_the_current_roles_workspace_menu(
    app_client: FlaskClient,
    role_accounts: dict[str, UserAccount],
    role: str,
    expected_links: tuple[str, ...],
    expected_labels: tuple[str, ...],
    forbidden_links: tuple[str, ...],
) -> None:
    login = _login(app_client, role_accounts[role].login_name or "")
    assert login.status_code == 302

    dashboard = app_client.get("/dashboard")
    body = dashboard.get_data(as_text=True)

    assert dashboard.status_code == 200
    for path in expected_links:
        assert f'href="{path}"' in body
    for label in expected_labels:
        assert label in body
    for path in forbidden_links:
        assert f'href="{path}"' not in body


def test_assistant_login_lands_on_approval_only_dashboard(
    app_client: FlaskClient,
    role_accounts: dict[str, UserAccount],
) -> None:
    login = _login(app_client, role_accounts["ASSISTANT_ADMIN"].login_name or "")

    assert login.status_code == 302
    assert login.headers["Location"].endswith("/dashboard")


def test_assistant_approval_queue_has_no_nonapproval_actions(
    app_client: FlaskClient,
    role_accounts: dict[str, UserAccount],
) -> None:
    _login(app_client, role_accounts["ASSISTANT_ADMIN"].login_name or "")
    approval_queue = app_client.get("/admin/members")
    approval_body = approval_queue.get_data(as_text=True)

    assert approval_queue.status_code == 200
    assert "계정 승인 요청" in approval_body
    assert "합성 승인 대기 계정" in approval_body
    assert "회원 승인" in approval_body
    assert 'href="/admin/consultations/new"' not in approval_body
    assert "역할 변경" not in approval_body


def test_assistant_cannot_access_teacher_or_main_admin_data_tools(
    app_client: FlaskClient,
    role_accounts: dict[str, UserAccount],
) -> None:
    _login(app_client, role_accounts["ASSISTANT_ADMIN"].login_name or "")
    statuses = {
        "/teacher/classrooms": app_client.get("/teacher/classrooms").status_code,
        "/admin/consultations/new": app_client.get("/admin/consultations/new").status_code,
        "/admin/ai/settings": app_client.get("/admin/ai/settings").status_code,
        "/teacher/outcomes": app_client.get("/teacher/outcomes").status_code,
        "/account/records": app_client.get("/account/records").status_code,
        "/admin/admission-results": app_client.get("/admin/admission-results").status_code,
        "/admin/sources": app_client.get("/admin/sources").status_code,
    }
    assert statuses == {
        "/teacher/classrooms": 403,
        "/admin/consultations/new": 403,
        "/admin/ai/settings": 403,
        "/teacher/outcomes": 403,
        "/account/records": 403,
        "/admin/admission-results": 403,
        "/admin/sources": 403,
    }


def test_student_and_teacher_can_store_isolated_encrypted_byok_keys(
    app_client: FlaskClient,
    role_accounts: dict[str, UserAccount],
    postgres_engine: Engine,
) -> None:
    student_key = "synthetic-student-byok-key"
    teacher_key = "synthetic-teacher-byok-key"

    _login(app_client, role_accounts["STUDENT"].login_name or "")
    student_settings = app_client.get("/admin/ai/settings")
    student_save = app_client.post(
        "/admin/ai/credentials",
        data={
            "csrf_token": _csrf(student_settings.get_data(as_text=True)),
            "provider": "OPENAI",
            "api_key": student_key,
        },
    )
    assert student_settings.status_code == 200
    assert student_save.status_code == 302

    with app_client.session_transaction() as browser_session:
        browser_session.clear()
    _login(app_client, role_accounts["TEACHER"].login_name or "")
    teacher_settings = app_client.get("/admin/ai/settings")
    teacher_save = app_client.post(
        "/admin/ai/credentials",
        data={
            "csrf_token": _csrf(teacher_settings.get_data(as_text=True)),
            "provider": "OPENAI",
            "api_key": teacher_key,
        },
    )
    assert teacher_settings.status_code == 200
    assert teacher_save.status_code == 302

    with Session(postgres_engine) as database_session:
        credentials = tuple(
            database_session.scalars(
                select(AiProviderCredential).where(
                    AiProviderCredential.actor_ref.in_(
                        (
                            role_accounts["STUDENT"].actor_ref,
                            role_accounts["TEACHER"].actor_ref,
                        )
                    )
                )
            )
        )
        assert len(credentials) == 2
        encrypted_by_actor = {
            credential.actor_ref: credential.encrypted_api_key for credential in credentials
        }
        assert student_key not in encrypted_by_actor[role_accounts["STUDENT"].actor_ref]
        assert teacher_key not in encrypted_by_actor[role_accounts["TEACHER"].actor_ref]
        assert len(set(encrypted_by_actor.values())) == 2


def test_admin_dashboard_exposes_full_governance_and_source_ingestion_menu(
    app_client: FlaskClient,
    role_accounts: dict[str, UserAccount],
) -> None:
    login = _login(app_client, role_accounts["ADMIN"].login_name or "")
    assert login.status_code == 302

    dashboard = app_client.get("/dashboard")
    body = dashboard.get_data(as_text=True)

    assert dashboard.status_code == 200
    expected_menu = {
        "/admin/members": "회원 역할·상태 관리",
        "/admin/admission-results": "입시결과 등록",
        "/admin/admission-results#procollege-collection": "전문대학포털 수집",
        "/admin/sources": "모집요강 자료 등록",
    }
    for path, label in expected_menu.items():
        assert f'href="{path}"' in body
        assert label in body
    assert "PDF" in body
    assert "PNG" in body


def test_real_admin_dashboard_also_exposes_teacher_workspace_menu(
    app_client: FlaskClient,
    role_accounts: dict[str, UserAccount],
) -> None:
    login = _login(app_client, role_accounts["ADMIN"].login_name or "")
    assert login.status_code == 302

    dashboard = app_client.get("/dashboard")
    body = dashboard.get_data(as_text=True)

    assert dashboard.status_code == 200
    expected_teacher_menu = {
        "/teacher/classrooms": "학과·학급 학생 관리",
        "/admin/ai/settings": "BYOK AI 설정",
        "/account/records": "저장 성적·상담 확인",
    }
    for path, label in expected_teacher_menu.items():
        assert f'href="{path}"' in body
        assert label in body
    assert "학생 상담자료 만들기" in body
