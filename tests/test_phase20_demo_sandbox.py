from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import (
    AiConsultationDraft,
    AiProviderCredential,
    InstitutionApplicationOutcome,
    StudentAcademicRecord,
    TeacherClassroom,
    UserAccount,
)
from app.services.demo_sandbox import (
    DemoSandboxError,
    active_demo_sandbox_credentials,
    authenticate_demo_sandbox_gateway,
    bootstrap_demo_sandbox,
    demo_sandbox_mode_enabled,
    purge_expired_demo_session_ai,
    require_demo_sandbox_config,
    reset_demo_role_accounts,
    sandbox_role_specs,
)
from app.services.membership import is_demo_actor_ref

VALID_CONFIG: dict[str, object] = {
    "DEMO_SANDBOX_ENABLED": True,
    "DEMO_SANDBOX_INSTANCE_ID": "public-v1",
    "DEMO_SANDBOX_PUBLIC_PASSWORD": "synthetic-public-password",
}


class UntouchedSession:
    def execute(self, *_args: object, **_kwargs: object) -> None:
        raise AssertionError("설정 검증 실패 전에는 DB를 호출하면 안 됩니다.")


def test_demo_mode_requires_explicit_parsed_boolean() -> None:
    assert demo_sandbox_mode_enabled(VALID_CONFIG)
    assert not demo_sandbox_mode_enabled({**VALID_CONFIG, "DEMO_SANDBOX_ENABLED": "true"})
    assert not demo_sandbox_mode_enabled({**VALID_CONFIG, "DEMO_SANDBOX_ENABLED": 1})

    with pytest.raises(DemoSandboxError, match="명시적으로"):
        require_demo_sandbox_config({**VALID_CONFIG, "DEMO_SANDBOX_ENABLED": "true"})


@pytest.mark.parametrize(
    ("key", "value", "message"),
    (
        ("DEMO_SANDBOX_INSTANCE_ID", "Production_DB", "인스턴스"),
        ("DEMO_SANDBOX_PUBLIC_PASSWORD", "short", "비밀번호"),
        ("DEMO_SANDBOX_PUBLIC_PASSWORD", "synthetic-password\n", "한 줄"),
    ),
)
def test_demo_config_rejects_unsafe_identifiers_and_credentials(
    key: str, value: object, message: str
) -> None:
    with pytest.raises(DemoSandboxError, match=message):
        require_demo_sandbox_config({**VALID_CONFIG, key: value})


def test_sandbox_roles_keep_real_role_boundaries_without_read_only_markers() -> None:
    settings = require_demo_sandbox_config(VALID_CONFIG)
    specs = sandbox_role_specs(settings)

    assert tuple(spec.role for spec in specs) == (
        "STUDENT",
        "TEACHER",
        "ADMIN",
        "ASSISTANT_ADMIN",
    )
    assert len({spec.login_name for spec in specs}) == 4
    assert len({spec.email for spec in specs}) == 4
    assert all(spec.actor_ref.startswith("sandbox:public-v1:role:") for spec in specs)
    assert all(not is_demo_actor_ref(spec.actor_ref) for spec in specs)


def test_disabled_reset_fails_before_database_access() -> None:
    with pytest.raises(DemoSandboxError, match="활성화"):
        reset_demo_role_accounts(
            UntouchedSession(),  # type: ignore[arg-type]
            config={**VALID_CONFIG, "DEMO_SANDBOX_ENABLED": False},
            occurred_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    ("login_name", "password"),
    (
        ("unknown-account", "synthetic-public-password"),
        ("demo-teacher", "wrong-public-password"),
    ),
)
def test_gateway_rejects_unknown_public_credentials_before_database_access(
    login_name: str, password: str
) -> None:
    assert (
        authenticate_demo_sandbox_gateway(
            UntouchedSession(),  # type: ignore[arg-type]
            config=VALID_CONFIG,
            login_name=login_name,
            password=password,
            occurred_at=datetime(2026, 7, 20, 12, 30, tzinfo=UTC),
        )
        is None
    )


def test_postgres_gateway_restores_only_requested_account_and_keeps_workspace(
    postgres_engine: Engine,
) -> None:
    connection = postgres_engine.connect()
    transaction = connection.begin()
    database_session = Session(bind=connection)
    try:
        accounts = reset_demo_role_accounts(
            database_session,
            config=VALID_CONFIG,
            occurred_at=datetime(2026, 7, 20, 13, 0, tzinfo=UTC),
        )
        teacher = next(account for account in accounts if account.role == "TEACHER")
        student = next(account for account in accounts if account.role == "STUDENT")
        classroom = TeacherClassroom(
            teacher_user_account_id=teacher.id,
            academic_year=2027,
            department_name="합성 게이트웨이 검증과",
            class_name="검증반",
        )
        database_session.add(classroom)
        database_session.flush()
        student_version = student.auth_version
        teacher_version = teacher.auth_version

        teacher.role = "MEMBER"
        teacher.status = "SUSPENDED"
        teacher.password_hash = generate_password_hash("visitor-changed-password")
        teacher.email_verified_at = None
        database_session.flush()

        credentials = active_demo_sandbox_credentials(
            database_session,
            config=VALID_CONFIG,
        )
        assert credentials is not None
        assert {credential.login_name for credential in credentials} == {
            "demo-student",
            "demo-teacher",
            "demo-main-admin",
            "demo-assistant-admin",
        }

        restored = authenticate_demo_sandbox_gateway(
            database_session,
            config=VALID_CONFIG,
            login_name="demo-teacher",
            password="synthetic-public-password",
            occurred_at=datetime(2026, 7, 20, 13, 5, tzinfo=UTC),
        )

        assert restored is teacher
        assert restored.role == "TEACHER"
        assert restored.status == "ACTIVE"
        assert restored.email_verified_at is not None
        assert restored.bootstrap_password_managed is False
        assert restored.password_hash is not None
        assert check_password_hash(restored.password_hash, "synthetic-public-password")
        assert restored.auth_version == teacher_version
        assert database_session.get(TeacherClassroom, classroom.id) is classroom
        assert (
            database_session.scalar(
                select(UserAccount.auth_version).where(UserAccount.id == student.id)
            )
            == student_version
        )
    finally:
        database_session.close()
        transaction.rollback()
        connection.close()


def test_postgres_bootstrap_uses_account_reference_for_student_seed_scores(
    postgres_engine: Engine,
) -> None:
    connection = postgres_engine.connect()
    transaction = connection.begin()
    database_session = Session(bind=connection)
    try:
        result = bootstrap_demo_sandbox(
            database_session,
            config=VALID_CONFIG,
            repository_root=Path(__file__).resolve().parents[1],
            occurred_at=datetime(2026, 7, 20, 14, 0, tzinfo=UTC),
        )
        student = next(account for account in result.accounts if account.role == "STUDENT")
        student_records = tuple(
            database_session.scalars(
                select(StudentAcademicRecord).where(
                    StudentAcademicRecord.owner_user_account_id == student.id
                )
            )
        )

        assert len(student_records) == 5
        assert {record.student_id for record in student_records} == {f"account:{student.id}"}
        assert len(result.public_data.source_institution_names) == 42
        assert result.synthetic_data.classroom_count == 2
        assert result.synthetic_data.classroom_student_count == 3
        assert result.synthetic_data.academic_record_count == 15
        assert result.synthetic_data.course_count == 93
        assert result.synthetic_data.outcome_count == 2

        assistant = next(
            account for account in result.accounts if account.role == "ASSISTANT_ADMIN"
        )
        assert (
            tuple(
                database_session.scalars(
                    select(TeacherClassroom).where(
                        TeacherClassroom.teacher_user_account_id == assistant.id
                    )
                )
            )
            == ()
        )
        assert (
            tuple(
                database_session.scalars(
                    select(StudentAcademicRecord).where(
                        StudentAcademicRecord.managed_by_user_account_id == assistant.id
                    )
                )
            )
            == ()
        )
        assert (
            tuple(
                database_session.scalars(
                    select(InstitutionApplicationOutcome).where(
                        InstitutionApplicationOutcome.managed_by_user_account_id == assistant.id
                    )
                )
            )
            == ()
        )

        original_year = student_records[0].academic_year
        original_version = student.auth_version
        student_records[0].academic_year = 2099
        database_session.flush()
        restored = authenticate_demo_sandbox_gateway(
            database_session,
            config=VALID_CONFIG,
            login_name="demo-student",
            password="synthetic-public-password",
            occurred_at=datetime(2026, 7, 20, 14, 5, tzinfo=UTC),
        )
        database_session.refresh(student_records[0])

        assert restored is student
        assert restored.auth_version == original_version
        assert student_records[0].academic_year == original_year
    finally:
        database_session.close()
        transaction.rollback()
        connection.close()


def test_postgres_purges_only_expired_session_scoped_sandbox_ai_rows(
    postgres_engine: Engine,
) -> None:
    now = datetime(2026, 7, 20, 15, 0, tzinfo=UTC)
    stale_actor = "sandbox:public-v1:role:STUDENT:session:stale-synthetic"
    fresh_actor = "sandbox:public-v1:role:STUDENT:session:fresh-synthetic"
    other_actor = "sandbox:other-v1:role:STUDENT:session:stale-synthetic"
    connection = postgres_engine.connect()
    transaction = connection.begin()
    database_session = Session(bind=connection)
    try:
        credentials = tuple(
            AiProviderCredential(
                actor_ref=actor,
                provider="OPENAI",
                encrypted_api_key="synthetic-ciphertext",
                masked_hint="••••1234",
                encryption_version="FERNET_V1",
                created_at=updated_at,
                updated_at=updated_at,
            )
            for actor, updated_at in (
                (stale_actor, now - timedelta(hours=7)),
                (fresh_actor, now - timedelta(hours=1)),
                (other_actor, now - timedelta(hours=7)),
            )
        )
        stale_draft = AiConsultationDraft(
            actor_ref=stale_actor,
            provider="OPENAI",
            model_name="synthetic-model",
            payload_schema_version=1,
            payload_digest="0" * 64,
            generated_text="합성 상담 초안입니다.",
            check_items=[],
            status="GENERATED_DRAFT",
            created_at=now - timedelta(hours=7),
            updated_at=now - timedelta(hours=7),
        )
        database_session.add_all((*credentials, stale_draft))
        database_session.flush()

        removed = purge_expired_demo_session_ai(
            database_session,
            config=VALID_CONFIG,
            occurred_at=now,
            max_age_seconds=21_600,
        )
        database_session.flush()

        assert removed == (1, 1)
        assert database_session.get(AiProviderCredential, credentials[0].id) is None
        assert database_session.get(AiConsultationDraft, stale_draft.id) is None
        assert database_session.get(AiProviderCredential, credentials[1].id) is not None
        assert database_session.get(AiProviderCredential, credentials[2].id) is not None
    finally:
        database_session.close()
        transaction.rollback()
        connection.close()
