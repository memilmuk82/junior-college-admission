from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import Engine, delete, or_, select
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app import create_app
from app.models import (
    AiConsultationDraft,
    AiProviderCredential,
    UserAccount,
    UserAccountAuditEvent,
)
from app.services.membership import (
    DEMO_ROLE_ACTOR_REFS,
    DEMO_ROLE_LOGIN_NAMES,
    MembershipError,
    approve_pending_member,
    bootstrap_admin,
    change_member_role,
    change_member_status,
    register_local_member,
)
from app.services.review_state import ReviewStateStore
from app.services.structured_imports import parse_structured_text
from app.services.temporary_uploads import TemporaryUploadStore

DEMO_PASSWORD = "phase17-public-demo-password"
TEST_ADMIN_LOGIN = "phase17-showcase-owner"
TEST_ADMIN_PASSWORD = "phase17-showcase-owner-password"


def _cleanup(postgres_engine: Engine) -> None:
    actor_refs = tuple(DEMO_ROLE_ACTOR_REFS.values())
    login_names = (*DEMO_ROLE_LOGIN_NAMES.values(), TEST_ADMIN_LOGIN, "phase17-collision")
    with Session(postgres_engine) as database_session:
        accounts = tuple(
            database_session.scalars(
                select(UserAccount).where(
                    or_(
                        UserAccount.actor_ref.in_(actor_refs),
                        UserAccount.login_name.in_(login_names),
                    )
                )
            )
        )
        account_ids = tuple(account.id for account in accounts)
        byok_refs = tuple(
            database_session.scalars(
                select(AiProviderCredential.actor_ref).where(
                    AiProviderCredential.actor_ref.like("demo:role:%:session:%")
                )
            )
        )
        if byok_refs:
            database_session.execute(
                delete(AiConsultationDraft).where(AiConsultationDraft.actor_ref.in_(byok_refs))
            )
            database_session.execute(
                delete(AiProviderCredential).where(AiProviderCredential.actor_ref.in_(byok_refs))
            )
        if account_ids:
            database_session.execute(
                delete(UserAccountAuditEvent).where(
                    or_(
                        UserAccountAuditEvent.target_user_id.in_(account_ids),
                        UserAccountAuditEvent.actor_user_id.in_(account_ids),
                    )
                )
            )
            database_session.execute(delete(UserAccount).where(UserAccount.id.in_(account_ids)))
        database_session.commit()


@pytest.fixture(autouse=True)
def clean_showcase_accounts(postgres_engine: Engine) -> Iterator[None]:
    _cleanup(postgres_engine)
    yield
    _cleanup(postgres_engine)


@pytest.fixture
def showcase_app(postgres_engine: Engine, tmp_path) -> Flask:  # type: ignore[no-untyped-def]
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "phase17-showcase-test-secret",
            "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            "ADMIN_USERNAME": TEST_ADMIN_LOGIN,
            "ADMIN_PASSWORD_HASH": generate_password_hash(TEST_ADMIN_PASSWORD),
            "ALLOW_LEGACY_ADMIN_LOGIN": False,
            "GOOGLE_OIDC_ENABLED": False,
            "TEMP_UPLOAD_ROOT": str(tmp_path / "uploads"),
            "BYOK_MASTER_KEY": Fernet.generate_key().decode("ascii"),
            "DEMO_LOGIN_NAME": "legacy-demo-no-longer-used",
            "DEMO_PUBLIC_PASSWORD": DEMO_PASSWORD,
        }
    )


def _csrf(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None
    return match.group(1)


def _bootstrap(app: Flask) -> None:
    runner = app.test_cli_runner()
    admin = runner.invoke(args=["auth", "bootstrap-admin"])
    assert admin.exit_code == 0, admin.output
    demo = runner.invoke(args=["auth", "bootstrap-demo"])
    assert demo.exit_code == 0, demo.output


def _login(client: FlaskClient, login_name: str):  # type: ignore[no-untyped-def]
    page = client.get("/auth/login")
    return client.post(
        "/auth/login",
        data={
            "csrf_token": _csrf(page.get_data(as_text=True)),
            "username": login_name,
            "password": DEMO_PASSWORD,
        },
    )


def _logout(client: FlaskClient) -> None:
    page = client.get("/dashboard")
    response = client.post(
        "/auth/logout",
        data={"csrf_token": _csrf(page.get_data(as_text=True))},
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/auth/login")


def _manual_form(csrf_token: str) -> dict[str, str]:
    return {
        "csrf_token": csrf_token,
        "input_mode": "manual",
        "student_profile": "VOCATIONAL_CURRENT",
        "rows-0-academic_year": "2025",
        "rows-0-grade": "1",
        "rows-0-semester": "1",
        "rows-0-subject_group": "국어",
        "rows-0-subject_name": "데모 공개 산출 합성 국어",
        "rows-0-credits": "4",
        "rows-0-raw_score": "",
        "rows-0-course_mean": "",
        "rows-0-standard_deviation": "",
        "rows-0-achievement_level": "",
        "rows-0-enrollment_count": "",
        "rows-0-rank_grade": "2",
    }


def test_demo_role_bootstrap_is_idempotent_and_login_page_lists_all_roles(
    showcase_app: Flask,
    postgres_engine: Engine,
) -> None:
    _bootstrap(showcase_app)
    _bootstrap(showcase_app)

    with Session(postgres_engine) as database_session:
        accounts = tuple(
            database_session.scalars(
                select(UserAccount)
                .where(UserAccount.actor_ref.in_(tuple(DEMO_ROLE_ACTOR_REFS.values())))
                .order_by(UserAccount.role)
            )
        )
        assert len(accounts) == 4
        assert {(account.login_name, account.role, account.status) for account in accounts} == {
            (DEMO_ROLE_LOGIN_NAMES[role], role, "ACTIVE") for role in DEMO_ROLE_LOGIN_NAMES
        }

    page = showcase_app.test_client().get("/auth/login")
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "역할 통합 로그인" in body
    assert body.count(DEMO_PASSWORD) == 1
    for login_name in DEMO_ROLE_LOGIN_NAMES.values():
        assert login_name in body
    for label in ("학생", "교사", "주 관리자", "보조 관리자"):
        assert label in body


def test_demo_role_bootstrap_collision_fails_closed_without_claiming_existing_account(
    showcase_app: Flask,
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine) as database_session:
        collision = register_local_member(
            database_session,
            login_name="phase17-collision",
            email="phase17-collision@example.invalid",
            display_name="합성 로그인 충돌 계정",
            password="phase17-collision-password",
            occurred_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        )
        collision.login_name = DEMO_ROLE_LOGIN_NAMES["STUDENT"]
        database_session.commit()

    runner = showcase_app.test_cli_runner()
    assert runner.invoke(args=["auth", "bootstrap-admin"]).exit_code == 0
    result = runner.invoke(args=["auth", "bootstrap-demo"])

    assert result.exit_code == 0
    assert "충돌" in result.output
    with Session(postgres_engine) as database_session:
        stored_collision = database_session.scalar(
            select(UserAccount).where(UserAccount.login_name == DEMO_ROLE_LOGIN_NAMES["STUDENT"])
        )
        assert stored_collision is not None
        assert stored_collision.actor_ref not in DEMO_ROLE_ACTOR_REFS.values()
        active_demo_count = len(
            tuple(
                database_session.scalars(
                    select(UserAccount).where(
                        UserAccount.actor_ref.in_(tuple(DEMO_ROLE_ACTOR_REFS.values())),
                        UserAccount.status == "ACTIVE",
                    )
                )
            )
        )
        assert active_demo_count == 0


@pytest.mark.parametrize(
    ("role", "heading"),
    (
        ("STUDENT", "학생 업무공간"),
        ("TEACHER", "교사 업무공간"),
        ("ADMIN", "주 관리자 업무공간"),
        ("ASSISTANT_ADMIN", "보조 관리자 승인 업무"),
    ),
)
def test_each_demo_role_logs_into_its_dashboard_and_logs_out(
    showcase_app: Flask,
    role: str,
    heading: str,
) -> None:
    _bootstrap(showcase_app)
    client = showcase_app.test_client()

    login = _login(client, DEMO_ROLE_LOGIN_NAMES[role])

    assert login.status_code == 302
    assert login.headers["Location"].endswith("/dashboard")
    dashboard = client.get("/dashboard")
    assert dashboard.status_code == 200
    assert heading in dashboard.get_data(as_text=True)
    _logout(client)
    assert client.get("/dashboard").status_code == 302


@pytest.mark.parametrize("role", ("ADMIN", "ASSISTANT_ADMIN"))
def test_demo_administrators_see_no_real_members_and_cannot_write(
    showcase_app: Flask,
    postgres_engine: Engine,
    role: str,
) -> None:
    _bootstrap(showcase_app)
    with Session(postgres_engine) as database_session:
        owner = database_session.scalar(
            select(UserAccount).where(UserAccount.login_name == TEST_ADMIN_LOGIN)
        )
        assert owner is not None
        pending = register_local_member(
            database_session,
            login_name="phase17-collision",
            email="hidden-member@example.invalid",
            display_name="화면에 노출되면 안 되는 회원",
            password="phase17-hidden-password",
            occurred_at=datetime(2026, 7, 20, 12, 5, tzinfo=UTC),
        )
        database_session.commit()
        pending_id = pending.id

    client = showcase_app.test_client()
    _login(client, DEMO_ROLE_LOGIN_NAMES[role])
    members = client.get("/admin/members")
    body = members.get_data(as_text=True)

    assert members.status_code == 200
    assert "읽기 전용 공개 체험" in body
    assert "화면에 노출되면 안 되는 회원" not in body
    assert "hidden-member@example.invalid" not in body
    blocked = client.post(
        f"/admin/members/{pending_id}/approve",
        data={"csrf_token": _csrf(body)},
    )
    assert blocked.status_code == 403


def test_demo_admin_does_not_weaken_last_real_admin_or_allow_reserved_target_mutation(
    showcase_app: Flask,
    postgres_engine: Engine,
) -> None:
    _bootstrap(showcase_app)
    with Session(postgres_engine) as database_session:
        real_admin = database_session.scalar(
            select(UserAccount).where(UserAccount.login_name == TEST_ADMIN_LOGIN)
        )
        demo_admin = database_session.scalar(
            select(UserAccount).where(UserAccount.actor_ref == DEMO_ROLE_ACTOR_REFS["ADMIN"])
        )
        demo_student = database_session.scalar(
            select(UserAccount).where(UserAccount.actor_ref == DEMO_ROLE_ACTOR_REFS["STUDENT"])
        )
        assert real_admin is not None
        assert demo_admin is not None
        assert demo_student is not None

        with pytest.raises(MembershipError, match="마지막 활성 관리자"):
            change_member_role(
                database_session,
                actor=real_admin,
                target=real_admin,
                new_role="MEMBER",
                occurred_at=datetime(2026, 7, 20, 12, 10, tzinfo=UTC),
            )
        with pytest.raises(MembershipError, match="마지막 활성 관리자"):
            change_member_status(
                database_session,
                actor=real_admin,
                target=real_admin,
                new_status="SUSPENDED",
                occurred_at=datetime(2026, 7, 20, 12, 11, tzinfo=UTC),
            )
        with pytest.raises(MembershipError, match="데모 계정의 역할"):
            change_member_role(
                database_session,
                actor=real_admin,
                target=demo_admin,
                new_role="MEMBER",
                occurred_at=datetime(2026, 7, 20, 12, 12, tzinfo=UTC),
            )
        with pytest.raises(MembershipError, match="데모 계정의 상태"):
            change_member_status(
                database_session,
                actor=real_admin,
                target=demo_admin,
                new_status="SUSPENDED",
                occurred_at=datetime(2026, 7, 20, 12, 13, tzinfo=UTC),
            )
        demo_student.status = "PENDING_APPROVAL"
        demo_student.approved_at = None
        demo_student.approved_by_user_id = None
        database_session.flush()
        with pytest.raises(MembershipError, match="데모 계정은 승인"):
            approve_pending_member(
                database_session,
                actor=real_admin,
                target=demo_student,
                occurred_at=datetime(2026, 7, 20, 12, 14, tzinfo=UTC),
            )

        database_session.refresh(real_admin)
        database_session.refresh(demo_admin)
        database_session.refresh(demo_student)
        assert (real_admin.role, real_admin.status) == ("ADMIN", "ACTIVE")
        assert (demo_admin.role, demo_admin.status) == ("ADMIN", "ACTIVE")
        assert demo_student.status == "PENDING_APPROVAL"


def test_real_admin_bootstrap_rejects_reserved_demo_login_and_actor(
    showcase_app: Flask,
    postgres_engine: Engine,
) -> None:
    with Session(postgres_engine) as database_session:
        with pytest.raises(MembershipError, match="예약 로그인 ID"):
            bootstrap_admin(
                database_session,
                login_name=DEMO_ROLE_LOGIN_NAMES["ADMIN"],
                password_hash=generate_password_hash("phase17-reserved-admin-password"),
                occurred_at=datetime(2026, 7, 20, 12, 15, tzinfo=UTC),
            )

    _bootstrap(showcase_app)
    with Session(postgres_engine) as database_session:
        demo_admin = database_session.scalar(
            select(UserAccount).where(UserAccount.actor_ref == DEMO_ROLE_ACTOR_REFS["ADMIN"])
        )
        assert demo_admin is not None
        demo_admin.login_name = "phase17-demo-admin-alias"
        database_session.commit()

        with pytest.raises(MembershipError, match="데모 계정"):
            bootstrap_admin(
                database_session,
                login_name="phase17-demo-admin-alias",
                password_hash=generate_password_hash("phase17-reserved-admin-password"),
                occurred_at=datetime(2026, 7, 20, 12, 16, tzinfo=UTC),
            )


def test_logged_in_demo_can_submit_public_example_scores_to_review(
    showcase_app: Flask,
) -> None:
    _bootstrap(showcase_app)
    client = showcase_app.test_client()
    assert _login(client, DEMO_ROLE_LOGIN_NAMES["STUDENT"]).status_code == 302

    start = client.get("/calculate?example=1")
    assert start.status_code == 200
    submitted = client.post(
        "/calculate/input",
        data=_manual_form(_csrf(start.get_data(as_text=True))),
        follow_redirects=True,
    )

    assert submitted.status_code == 200
    assert "학생 성적 입력 검수" in submitted.get_data(as_text=True)
    assert "데모 공개 산출 합성 국어" in submitted.get_data(as_text=True)


def test_demo_review_allowlist_rejects_non_anonymous_import_confirmation(
    showcase_app: Flask,
) -> None:
    _bootstrap(showcase_app)
    client = showcase_app.test_client()
    assert _login(client, DEMO_ROLE_LOGIN_NAMES["STUDENT"]).status_code == 302
    store = TemporaryUploadStore(showcase_app.config["TEMP_UPLOAD_ROOT"])
    review_session_id = store.create_session()
    preview = parse_structured_text(
        "학년도,학년,학기,교과,과목,이수단위,석차등급\n"
        "2025,1,1,국어,데모 비공개 import 합성 과목,4,2",
        source_format="csv",
    )
    ReviewStateStore(store).save(
        review_session_id,
        preview,
        student_id="synthetic-non-anonymous-student",
        record_source="HOME_SCHOOL_RECORD",
        owner_actor_ref=DEMO_ROLE_ACTOR_REFS["STUDENT"],
    )

    calculate = client.get("/calculate")
    token = _csrf(calculate.get_data(as_text=True))
    assert client.get(f"/input/review/{review_session_id}").status_code == 403
    assert (
        client.post(f"/input/review/{review_session_id}", data={"csrf_token": token}).status_code
        == 403
    )
    assert (
        client.post(
            f"/input/review/{review_session_id}/discard", data={"csrf_token": token}
        ).status_code
        == 403
    )
    assert store.session_path(review_session_id).is_dir()


def test_demo_operational_views_are_empty_and_sensitive_get_exports_are_blocked(
    showcase_app: Flask,
) -> None:
    _bootstrap(showcase_app)
    client = showcase_app.test_client()
    assert _login(client, DEMO_ROLE_LOGIN_NAMES["ADMIN"]).status_code == 302

    for path, notice in (
        ("/admin/rules", "실제 규칙 초안"),
        ("/admin/sources", "실제 업로드 파일명"),
        ("/admin/admission-results", "실제 import 데이터셋"),
        ("/teacher/outcomes", "실제 기관 내부 학생 코드"),
        ("/account/records", "읽기 전용 체험 계정"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert notice in response.get_data(as_text=True)

    for path in (
        "/admin/rules/SCORE_RULE/synthetic-rule/edit",
        "/admin/rules/SCORE_RULE/synthetic-rule",
        "/admin/rules/csv",
        "/admin/rules/csv/export",
        "/admin/verified-source-rules",
        "/admin/admission-results/synthetic-dataset",
        "/teacher/outcomes.csv",
        "/account/consultations/synthetic-consultation/clone",
        "/account/consultations/synthetic-consultation/print/student",
        "/account/consultations/synthetic-consultation/print/teacher",
    ):
        assert client.get(path).status_code == 403
    assert client.get("/teacher/classrooms").status_code == 403

    _logout(client)
    assert _login(client, DEMO_ROLE_LOGIN_NAMES["TEACHER"]).status_code == 302
    classrooms = client.get("/teacher/classrooms")
    assert classrooms.status_code == 200
    assert "실제 학급·익명 학생·성적" in classrooms.get_data(as_text=True)
    assert client.get("/teacher/outcomes.csv").status_code == 403


@pytest.mark.parametrize("invalidator", ("version", "delete"))
def test_invalid_demo_session_purges_session_scoped_byok_before_clearing_auth(
    showcase_app: Flask,
    postgres_engine: Engine,
    invalidator: str,
) -> None:
    _bootstrap(showcase_app)
    client = showcase_app.test_client()
    assert _login(client, DEMO_ROLE_LOGIN_NAMES["STUDENT"]).status_code == 302
    settings = client.get("/admin/ai/settings")
    saved = client.post(
        "/admin/ai/credentials",
        data={
            "csrf_token": _csrf(settings.get_data(as_text=True)),
            "provider": "OPENAI",
            "api_key": "synthetic-invalid-session-key-1234",
        },
    )
    assert saved.status_code == 302
    with client.session_transaction() as browser_session:
        owner_ref = browser_session["demo_byok_actor_ref"]
        user_id = browser_session["user_id"]

    with Session(postgres_engine) as database_session:
        account = database_session.get(UserAccount, user_id)
        assert account is not None
        if invalidator == "version":
            account.auth_version += 1
        else:
            database_session.execute(
                delete(UserAccountAuditEvent).where(
                    or_(
                        UserAccountAuditEvent.target_user_id == user_id,
                        UserAccountAuditEvent.actor_user_id == user_id,
                    )
                )
            )
            database_session.delete(account)
        database_session.commit()

    invalidated = client.get("/dashboard")
    assert invalidated.status_code == 302
    assert "/auth/login" in invalidated.headers["Location"]
    with client.session_transaction() as browser_session:
        assert "user_id" not in browser_session
        assert "demo_byok_actor_ref" not in browser_session
    with Session(postgres_engine) as database_session:
        assert (
            database_session.scalar(
                select(AiProviderCredential).where(AiProviderCredential.actor_ref == owner_ref)
            )
            is None
        )


def test_records_login_registration_and_logout_navigation_preserves_next(
    showcase_app: Flask,
) -> None:
    _bootstrap(showcase_app)
    client = showcase_app.test_client()
    login = client.get("/auth/login?account_type=student&next=/account/records")
    login_body = login.get_data(as_text=True)
    assert "account_type=student" in login_body
    assert "next=/account/records" in login_body

    registration = client.get("/auth/register?account_type=student&next=/account/records")
    registration_body = registration.get_data(as_text=True)
    assert 'name="next" value="/account/records"' in registration_body
    assert "next=/account/records" in registration_body
    received = client.get("/auth/registration-received?account_type=student&next=/account/records")
    assert "next=/account/records" in received.get_data(as_text=True)

    logged_in = client.post(
        "/auth/login",
        data={
            "csrf_token": _csrf(login_body),
            "username": DEMO_ROLE_LOGIN_NAMES["STUDENT"],
            "password": DEMO_PASSWORD,
            "next": "/account/records",
        },
    )
    assert logged_in.status_code == 302
    assert logged_in.headers["Location"].endswith("/account/records")
    records = client.get("/account/records")
    assert records.status_code == 200
    assert 'action="/auth/logout"' in records.get_data(as_text=True)


def test_demo_student_and_teacher_byok_is_encrypted_session_scoped_and_purged_on_logout(
    showcase_app: Flask,
    postgres_engine: Engine,
) -> None:
    _bootstrap(showcase_app)
    student_a = showcase_app.test_client()
    student_b = showcase_app.test_client()
    teacher = showcase_app.test_client()
    assert _login(student_a, DEMO_ROLE_LOGIN_NAMES["STUDENT"]).status_code == 302
    assert _login(student_b, DEMO_ROLE_LOGIN_NAMES["STUDENT"]).status_code == 302
    assert _login(teacher, DEMO_ROLE_LOGIN_NAMES["TEACHER"]).status_code == 302

    keys = {
        student_a: "synthetic-session-student-a-1111",
        student_b: "synthetic-session-student-b-2222",
        teacher: "synthetic-session-teacher-3333",
    }
    owner_refs: dict[FlaskClient, str] = {}
    for client, api_key in keys.items():
        settings = client.get("/admin/ai/settings")
        assert settings.status_code == 200
        saved = client.post(
            "/admin/ai/credentials",
            data={
                "csrf_token": _csrf(settings.get_data(as_text=True)),
                "provider": "OPENAI",
                "api_key": api_key,
            },
            follow_redirects=True,
        )
        body = saved.get_data(as_text=True)
        assert saved.status_code == 200
        assert f"••••{api_key[-4:]}" in body
        assert api_key not in body
        with client.session_transaction() as browser_session:
            owner_ref = browser_session.get("demo_byok_actor_ref")
            assert isinstance(owner_ref, str)
            owner_refs[client] = owner_ref

    assert len(set(owner_refs.values())) == 3
    assert student_b.get("/admin/ai/settings").get_data(as_text=True).find("••••1111") == -1
    assert teacher.get("/admin/ai/settings").get_data(as_text=True).find("••••2222") == -1

    with Session(postgres_engine) as database_session:
        credentials = tuple(
            database_session.scalars(
                select(AiProviderCredential).where(
                    AiProviderCredential.actor_ref.in_(tuple(owner_refs.values()))
                )
            )
        )
        assert len(credentials) == 3
        for credential in credentials:
            assert all(api_key not in credential.encrypted_api_key for api_key in keys.values())

        database_session.add(
            AiConsultationDraft(
                actor_ref=owner_refs[student_b],
                provider="OPENAI",
                model_name="synthetic-model",
                payload_schema_version=2,
                payload_digest="f" * 64,
                generated_text="로그아웃과 함께 삭제될 합성 초안입니다.",
                check_items=[],
                status="GENERATED_DRAFT",
            )
        )
        database_session.commit()

    settings_a = student_a.get("/admin/ai/settings")
    deleted = student_a.post(
        "/admin/ai/credentials/OPENAI/delete",
        data={"csrf_token": _csrf(settings_a.get_data(as_text=True))},
    )
    assert deleted.status_code == 302
    with Session(postgres_engine) as database_session:
        assert (
            database_session.scalar(
                select(AiProviderCredential).where(
                    AiProviderCredential.actor_ref == owner_refs[student_a]
                )
            )
            is None
        )
        assert (
            database_session.scalar(
                select(AiProviderCredential).where(
                    AiProviderCredential.actor_ref == owner_refs[student_b]
                )
            )
            is not None
        )

    _logout(student_b)
    with Session(postgres_engine) as database_session:
        assert (
            database_session.scalar(
                select(AiProviderCredential).where(
                    AiProviderCredential.actor_ref == owner_refs[student_b]
                )
            )
            is None
        )
        assert (
            database_session.scalar(
                select(AiConsultationDraft).where(
                    AiConsultationDraft.actor_ref == owner_refs[student_b]
                )
            )
            is None
        )
        assert (
            database_session.scalar(
                select(AiProviderCredential).where(
                    AiProviderCredential.actor_ref == owner_refs[teacher]
                )
            )
            is not None
        )

    _logout(teacher)


def test_demo_unsafe_requests_and_ai_generation_are_blocked_except_key_management(
    showcase_app: Flask,
) -> None:
    _bootstrap(showcase_app)
    client = showcase_app.test_client()
    _login(client, DEMO_ROLE_LOGIN_NAMES["STUDENT"])
    settings = client.get("/admin/ai/settings")
    token = _csrf(settings.get_data(as_text=True))

    assert (
        client.post(
            "/admin/consultations/ai-draft",
            data={"csrf_token": token},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/account/classroom-links",
            data={"csrf_token": token},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/calculate/synthetic-calculation/save",
            data={"csrf_token": token},
        ).status_code
        == 403
    )
