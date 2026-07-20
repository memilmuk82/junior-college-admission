from __future__ import annotations

import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, uuid5

import click
from flask import Flask
from flask.cli import AppGroup
from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session
from werkzeug.security import generate_password_hash

from app.database import db
from app.models import (
    AccountAuthToken,
    AdmissionRound,
    AdmissionTrack,
    AiConsultationDraft,
    AiProviderCredential,
    Campus,
    ClassroomStudent,
    ExternalIdentity,
    Institution,
    InstitutionApplicationOutcome,
    Program,
    StudentAcademicRecord,
    StudentCourseRecord,
    TeacherClassroom,
    UserAccount,
    new_id,
)
from app.services.classroom_links import classroom_student_reference
from app.services.demo_scores import DEMO_SCORE_ROWS
from app.services.membership import DEMO_ROLE_SPECS, is_demo_actor_ref
from app.services.phase14_public_seed import Phase17PublicSeedResult, load_phase17_public_seed
from app.services.verified_source_rules import (
    confirm_verified_source_rule,
    load_verified_source_rules,
)

DEMO_SANDBOX_LOCK_KEY = 780_331_006_507_120_020
INSTANCE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,31}\Z")


class DemoSandboxError(RuntimeError):
    """Raised before any mutation when the isolated demo contract is not satisfied."""


@dataclass(frozen=True, slots=True)
class DemoSandboxSettings:
    instance_id: str
    public_password: str


@dataclass(frozen=True, slots=True)
class DemoSandboxRoleSpec:
    role: str
    label: str
    login_name: str
    actor_ref: str
    email: str
    display_name: str


@dataclass(frozen=True, slots=True)
class DemoSyntheticSeedResult:
    classroom_count: int
    classroom_student_count: int
    academic_record_count: int
    course_count: int
    outcome_count: int


@dataclass(frozen=True, slots=True)
class DemoSandboxBootstrapResult:
    accounts: tuple[UserAccount, ...]
    public_data: Phase17PublicSeedResult
    synthetic_data: DemoSyntheticSeedResult
    verified_rule_confirmation_count: int


@dataclass(frozen=True, slots=True)
class DemoSandboxCredential:
    role: str
    label: str
    login_name: str
    public_password: str


def demo_sandbox_mode_enabled(config: Mapping[str, object]) -> bool:
    """Only an explicitly parsed boolean enables destructive sandbox setup."""

    return config.get("DEMO_SANDBOX_ENABLED") is True


def require_demo_sandbox_config(config: Mapping[str, object]) -> DemoSandboxSettings:
    """Validate the independent demo-process marker and its public credential.

    The application factory must parse ``DEMO_SANDBOX_ENABLED`` to a boolean. Raw
    environment strings are deliberately rejected so a misspelled or loosely
    truthy production value can never enable this mutating bootstrap.
    """

    if not demo_sandbox_mode_enabled(config):
        raise DemoSandboxError("격리 체험 모드가 명시적으로 활성화되지 않았습니다.")
    instance_id = config.get("DEMO_SANDBOX_INSTANCE_ID")
    if not isinstance(instance_id, str) or INSTANCE_ID_PATTERN.fullmatch(instance_id) is None:
        raise DemoSandboxError("체험 인스턴스 식별자는 영문 소문자·숫자·하이픈 1~32자입니다.")
    password = config.get("DEMO_SANDBOX_PUBLIC_PASSWORD") or config.get("DEMO_PUBLIC_PASSWORD")
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise DemoSandboxError("체험 공개 비밀번호는 12~256자로 별도 설정해야 합니다.")
    if "\n" in password or "\r" in password:
        raise DemoSandboxError("체험 공개 비밀번호는 한 줄 값이어야 합니다.")
    return DemoSandboxSettings(instance_id=instance_id, public_password=password)


def sandbox_role_specs(settings: DemoSandboxSettings) -> tuple[DemoSandboxRoleSpec, ...]:
    """Build writable sandbox actors without the production read-only demo marker."""

    specs = tuple(
        DemoSandboxRoleSpec(
            role=source.role,
            label=source.label,
            login_name=source.login_name,
            actor_ref=f"sandbox:{settings.instance_id}:role:{source.role}",
            email=source.email,
            display_name=f"체험 {source.label}",
        )
        for source in DEMO_ROLE_SPECS
    )
    if any(is_demo_actor_ref(spec.actor_ref) for spec in specs):
        raise DemoSandboxError("체험 계정이 운영 공개 계정의 읽기 전용 표식과 충돌합니다.")
    return specs


def reset_demo_role_accounts(
    session: Session,
    *,
    config: Mapping[str, object],
    occurred_at: datetime,
) -> tuple[UserAccount, ...]:
    """Restore the four known credentials and roles inside an isolated database."""

    settings = require_demo_sandbox_config(config)
    _require_aware_time(occurred_at)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": DEMO_SANDBOX_LOCK_KEY},
    )
    return _reset_demo_role_accounts(session, settings=settings, occurred_at=occurred_at)


def active_demo_sandbox_credentials(
    session: Session,
    *,
    config: Mapping[str, object],
) -> tuple[DemoSandboxCredential, ...] | None:
    """Return fixed gateway credentials when all four stable sandbox actors exist.

    Mutable email, password, role, and status fields are intentionally ignored:
    the gateway restores only the selected account when a visitor starts a new
    session with the displayed fixed credential.
    """

    settings = require_demo_sandbox_config(config)
    specs = sandbox_role_specs(settings)
    accounts = tuple(
        session.scalars(
            select(UserAccount).where(
                UserAccount.actor_ref.in_(tuple(spec.actor_ref for spec in specs))
            )
        )
    )
    actor_refs = {account.actor_ref for account in accounts}
    credentials: list[DemoSandboxCredential] = []
    for spec in specs:
        if spec.actor_ref not in actor_refs:
            return None
        credentials.append(
            DemoSandboxCredential(
                role=spec.role,
                label=spec.label,
                login_name=spec.login_name,
                public_password=settings.public_password,
            )
        )
    return tuple(credentials)


def authenticate_demo_sandbox_gateway(
    session: Session,
    *,
    config: Mapping[str, object],
    login_name: str,
    password: str,
    occurred_at: datetime,
) -> UserAccount | None:
    """Authenticate a fixed public credential and repair the shared baseline.

    This helper is intended to run only for a new login attempt. It restores
    fixed role/account state and the known synthetic seed rows that a previous
    visitor may have changed. Visitor-added rows remain available until an
    operator resets the isolated demo volume. Existing sessions are not revoked
    merely because another visitor starts the same public role.
    """

    settings = require_demo_sandbox_config(config)
    _require_aware_time(occurred_at)
    normalized_login = login_name.strip().lower()
    requested_spec = next(
        (
            spec
            for spec in sandbox_role_specs(settings)
            if hmac.compare_digest(spec.login_name, normalized_login)
        ),
        None,
    )
    password_matches = hmac.compare_digest(
        password.encode("utf-8"), settings.public_password.encode("utf-8")
    )
    if requested_spec is None or not password_matches:
        return None
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": DEMO_SANDBOX_LOCK_KEY},
    )
    specs = sandbox_role_specs(settings)
    accounts = tuple(
        session.scalars(
            select(UserAccount)
            .where(UserAccount.actor_ref.in_(tuple(spec.actor_ref for spec in specs)))
            .order_by(UserAccount.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    accounts_by_actor = {account.actor_ref: account for account in accounts}
    if len(accounts_by_actor) != len(specs):
        raise DemoSandboxError("체험 DB를 먼저 bootstrap 해야 합니다.")
    for spec in specs:
        account = accounts_by_actor[spec.actor_ref]
        identity_owner = session.scalar(
            select(UserAccount.id).where(
                or_(
                    UserAccount.login_name == spec.login_name,
                    UserAccount.email == spec.email,
                ),
                UserAccount.id != account.id,
            )
        )
        if identity_owner is not None:
            raise DemoSandboxError("체험 계정 예약 식별자가 다른 계정과 충돌합니다.")

    admin_spec = next(spec for spec in specs if spec.role == "ADMIN")
    main_admin = accounts_by_actor[admin_spec.actor_ref]
    account = accounts_by_actor[requested_spec.actor_ref]
    for spec in specs:
        role_account = accounts_by_actor[spec.actor_ref]
        role_account.login_name = spec.login_name
        role_account.email = spec.email
        role_account.display_name = spec.display_name
        role_account.password_hash = generate_password_hash(settings.public_password)
        role_account.role = spec.role
        role_account.status = "ACTIVE"
        role_account.email_verified_at = occurred_at
        role_account.bootstrap_password_managed = False
        role_account.approved_by_user_id = (
            role_account.id if role_account is main_admin else main_admin.id
        )
        role_account.approved_at = occurred_at
    account.last_login_at = occurred_at
    session.execute(delete(AccountAuthToken).where(AccountAuthToken.user_account_id == account.id))
    session.execute(delete(ExternalIdentity).where(ExternalIdentity.user_account_id == account.id))
    session.flush()
    if session.scalar(select(AdmissionTrack.id).limit(1)) is not None:
        _seed_synthetic_workspace(
            session,
            settings=settings,
            accounts=tuple(accounts_by_actor[spec.actor_ref] for spec in specs),
            occurred_at=occurred_at,
        )
    return account


def seed_demo_synthetic_workspace(
    session: Session,
    *,
    config: Mapping[str, object],
    occurred_at: datetime,
) -> DemoSyntheticSeedResult:
    """Idempotently restore explicitly synthetic classroom, score and outcome rows."""

    settings = require_demo_sandbox_config(config)
    _require_aware_time(occurred_at)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": DEMO_SANDBOX_LOCK_KEY},
    )
    accounts = _load_role_accounts(session, settings=settings)
    return _seed_synthetic_workspace(
        session,
        settings=settings,
        accounts=accounts,
        occurred_at=occurred_at,
    )


def bootstrap_demo_sandbox(
    session: Session,
    *,
    config: Mapping[str, object],
    repository_root: Path,
    occurred_at: datetime,
) -> DemoSandboxBootstrapResult:
    """CLI-callable all-in-one setup for an independently deployed demo database.

    The caller owns commit/rollback. Production code must never pass its database
    session to this function; the exact boolean mode gate above is the final local
    safeguard, while the separate container/database is the isolation boundary.
    """

    settings = require_demo_sandbox_config(config)
    _require_aware_time(occurred_at)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": DEMO_SANDBOX_LOCK_KEY},
    )
    accounts = _reset_demo_role_accounts(session, settings=settings, occurred_at=occurred_at)
    main_admin = next(account for account in accounts if account.role == "ADMIN")
    public_data = load_phase17_public_seed(
        session,
        repository_root=repository_root,
        actor_ref=main_admin.actor_ref,
        occurred_at=occurred_at,
    )
    verified_rule_confirmation_count = _confirm_verified_source_rules(
        session,
        repository_root=repository_root,
        main_admin=main_admin,
    )
    synthetic_data = _seed_synthetic_workspace(
        session,
        settings=settings,
        accounts=accounts,
        occurred_at=occurred_at,
    )
    return DemoSandboxBootstrapResult(
        accounts=accounts,
        public_data=public_data,
        synthetic_data=synthetic_data,
        verified_rule_confirmation_count=verified_rule_confirmation_count,
    )


def purge_expired_demo_session_ai(
    session: Session,
    *,
    config: Mapping[str, object],
    occurred_at: datetime,
    max_age_seconds: int,
) -> tuple[int, int]:
    """Remove abandoned per-browser BYOK rows from only this sandbox instance."""

    settings = require_demo_sandbox_config(config)
    _require_aware_time(occurred_at)
    if isinstance(max_age_seconds, bool) or not 300 <= max_age_seconds <= 604_800:
        raise DemoSandboxError("체험 BYOK 보존 시간은 300~604800초여야 합니다.")
    cutoff = occurred_at - timedelta(seconds=max_age_seconds)
    actor_pattern = f"sandbox:{settings.instance_id}:role:%:session:%"
    draft_ids = tuple(
        session.scalars(
            select(AiConsultationDraft.id).where(
                AiConsultationDraft.actor_ref.like(actor_pattern),
                AiConsultationDraft.updated_at < cutoff,
            )
        )
    )
    credential_ids = tuple(
        session.scalars(
            select(AiProviderCredential.id).where(
                AiProviderCredential.actor_ref.like(actor_pattern),
                AiProviderCredential.updated_at < cutoff,
            )
        )
    )
    if draft_ids:
        session.execute(delete(AiConsultationDraft).where(AiConsultationDraft.id.in_(draft_ids)))
    if credential_ids:
        session.execute(
            delete(AiProviderCredential).where(AiProviderCredential.id.in_(credential_ids))
        )
    return len(credential_ids), len(draft_ids)


def register_demo_sandbox_cli(app: Flask) -> None:
    """Register the isolated runtime's ``flask demo-sandbox bootstrap`` command."""

    group = AppGroup("demo-sandbox")

    @group.command("bootstrap")
    def bootstrap_command() -> None:
        """Restore base accounts and seed reviewed public/synthetic demo data."""

        try:
            result = bootstrap_demo_sandbox(
                cast(Session, db.session),
                config=app.config,
                repository_root=Path(app.root_path).parent,
                occurred_at=datetime.now(UTC),
            )
            institution_count = db.session.scalar(select(func.count()).select_from(Institution))
            program_count = db.session.scalar(select(func.count()).select_from(Program))
            track_count = db.session.scalar(select(func.count()).select_from(AdmissionTrack))
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        click.echo(
            "demo sandbox ready: "
            f"accounts={len(result.accounts)} "
            f"source_institutions={len(result.public_data.source_institution_names)} "
            f"institutions={institution_count} programs={program_count} tracks={track_count} "
            f"verified_rules={result.verified_rule_confirmation_count} "
            f"classrooms={result.synthetic_data.classroom_count} "
            f"scores={result.synthetic_data.course_count} "
            f"outcomes={result.synthetic_data.outcome_count}"
        )

    @group.command("purge-session-ai")
    @click.option(
        "--max-age-seconds",
        type=click.IntRange(min=300, max=604_800),
        default=21_600,
        show_default=True,
    )
    def purge_session_ai_command(max_age_seconds: int) -> None:
        """Purge abandoned encrypted demo BYOK credentials and drafts."""

        try:
            credential_count, draft_count = purge_expired_demo_session_ai(
                cast(Session, db.session),
                config=app.config,
                occurred_at=datetime.now(UTC),
                max_age_seconds=max_age_seconds,
            )
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        click.echo(
            f"demo session AI cleanup complete: credentials={credential_count} drafts={draft_count}"
        )

    app.cli.add_command(group)


def _require_aware_time(value: datetime) -> None:
    if value.tzinfo is None:
        raise DemoSandboxError("체험 데이터 처리 시각에는 시간대가 필요합니다.")


def _stable_id(settings: DemoSandboxSettings, kind: str, key: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"admission-demo-sandbox:{settings.instance_id}:{kind}:{key}"))


def _reset_demo_role_accounts(
    session: Session,
    *,
    settings: DemoSandboxSettings,
    occurred_at: datetime,
) -> tuple[UserAccount, ...]:
    specs = sandbox_role_specs(settings)
    actor_refs = tuple(spec.actor_ref for spec in specs)
    existing_by_actor = {
        account.actor_ref: account
        for account in session.scalars(
            select(UserAccount)
            .where(UserAccount.actor_ref.in_(actor_refs))
            .order_by(UserAccount.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    }
    for spec in specs:
        identity_owner = session.scalar(
            select(UserAccount)
            .where(
                or_(
                    UserAccount.login_name == spec.login_name,
                    UserAccount.email == spec.email,
                ),
                UserAccount.actor_ref != spec.actor_ref,
            )
            .with_for_update()
        )
        if identity_owner is not None:
            raise DemoSandboxError("체험 계정 예약 식별자가 다른 계정과 충돌합니다.")

    admin_spec = next(spec for spec in specs if spec.role == "ADMIN")
    ordered_specs = (admin_spec, *(spec for spec in specs if spec.role != "ADMIN"))
    accounts_by_actor: dict[str, UserAccount] = {}
    for spec in ordered_specs:
        account = existing_by_actor.get(spec.actor_ref)
        if account is None:
            account = UserAccount(
                id=new_id(),
                actor_ref=spec.actor_ref,
                login_name=spec.login_name,
                email=spec.email,
                display_name=spec.display_name,
                password_hash=generate_password_hash(settings.public_password),
                role=spec.role,
                status="ACTIVE",
                auth_version=1,
                email_verified_at=occurred_at,
                bootstrap_password_managed=False,
                approved_at=occurred_at,
            )
            account.approved_by_user_id = account.id
            session.add(account)
            session.flush()
        accounts_by_actor[spec.actor_ref] = account

    main_admin = accounts_by_actor[admin_spec.actor_ref]
    for spec in ordered_specs:
        account = accounts_by_actor[spec.actor_ref]
        if account.actor_ref in existing_by_actor:
            account.auth_version += 1
        account.login_name = spec.login_name
        account.email = spec.email
        account.display_name = spec.display_name
        account.password_hash = generate_password_hash(settings.public_password)
        account.role = spec.role
        account.status = "ACTIVE"
        account.email_verified_at = occurred_at
        account.bootstrap_password_managed = False
        account.approved_by_user_id = account.id if account is main_admin else main_admin.id
        account.approved_at = occurred_at
        account.last_login_at = None
    session.flush()

    account_ids = tuple(account.id for account in accounts_by_actor.values())
    session.execute(
        delete(AccountAuthToken).where(AccountAuthToken.user_account_id.in_(account_ids))
    )
    session.execute(
        delete(ExternalIdentity).where(ExternalIdentity.user_account_id.in_(account_ids))
    )
    return tuple(accounts_by_actor[spec.actor_ref] for spec in specs)


def _load_role_accounts(
    session: Session, *, settings: DemoSandboxSettings
) -> tuple[UserAccount, ...]:
    specs = sandbox_role_specs(settings)
    accounts = tuple(
        session.scalars(
            select(UserAccount).where(
                UserAccount.actor_ref.in_(tuple(spec.actor_ref for spec in specs))
            )
        )
    )
    by_actor = {account.actor_ref: account for account in accounts}
    ordered: list[UserAccount] = []
    for spec in specs:
        account = by_actor.get(spec.actor_ref)
        if (
            account is None
            or account.login_name != spec.login_name
            or account.email != spec.email
            or account.role != spec.role
            or account.status != "ACTIVE"
        ):
            raise DemoSandboxError("먼저 체험 역할 계정을 초기화해야 합니다.")
        ordered.append(account)
    return tuple(ordered)


def _confirm_verified_source_rules(
    session: Session,
    *,
    repository_root: Path,
    main_admin: UserAccount,
) -> int:
    """Confirm only the repository's reviewed official-source fallback rules.

    This intentionally does not synthesize PUBLISHED database rules. Batch
    consultation uses these key-matched VERIFIED_SOURCE definitions for the
    small reviewed subset; every other Phase 17 program remains visibly in the
    calculation-preparation state.
    """

    rule_path = repository_root / "data" / "seed" / "phase14_verified_source_rules.json"
    confirmed = 0
    for rule in load_verified_source_rules(rule_path):
        if rule.execution_status != "VERIFIED_SOURCE":
            continue
        confirm_verified_source_rule(session, rule=rule, actor=main_admin)
        confirmed += 1
    return confirmed


def _seed_synthetic_workspace(
    session: Session,
    *,
    settings: DemoSandboxSettings,
    accounts: tuple[UserAccount, ...],
    occurred_at: datetime,
) -> DemoSyntheticSeedResult:
    accounts_by_role = {account.role: account for account in accounts}
    student_account = accounts_by_role["STUDENT"]
    teacher_accounts = tuple(
        account for account in accounts if account.role in {"TEACHER", "ADMIN"}
    )

    record_count, course_count = _seed_score_rows(
        session,
        settings=settings,
        owner=student_account,
        managed_by=None,
        student_id=f"account:{student_account.id}",
        key="student-account",
    )
    classroom_count = 0
    classroom_student_count = 0
    for teacher in teacher_accounts:
        classroom = _upsert_classroom(session, settings=settings, teacher=teacher)
        classroom_count += 1
        if teacher.role == "TEACHER":
            _upsert_classroom_student(
                session,
                settings=settings,
                classroom=classroom,
                key=f"{teacher.role}:linked",
                anonymous_code="LINKED-001",
                linked_account=student_account,
                occurred_at=occurred_at,
            )
            classroom_student_count += 1
        managed_student = _upsert_classroom_student(
            session,
            settings=settings,
            classroom=classroom,
            key=f"{teacher.role}:managed",
            anonymous_code="SYNTH-001",
            linked_account=None,
            occurred_at=occurred_at,
        )
        classroom_student_count += 1
        added_records, added_courses = _seed_score_rows(
            session,
            settings=settings,
            owner=None,
            managed_by=teacher,
            student_id=classroom_student_reference(managed_student.id),
            key=f"{teacher.role}:managed",
        )
        record_count += added_records
        course_count += added_courses

    outcome_count = _seed_outcomes(
        session,
        settings=settings,
        teachers=teacher_accounts,
    )
    session.flush()
    return DemoSyntheticSeedResult(
        classroom_count=classroom_count,
        classroom_student_count=classroom_student_count,
        academic_record_count=record_count,
        course_count=course_count,
        outcome_count=outcome_count,
    )


def _upsert_classroom(
    session: Session,
    *,
    settings: DemoSandboxSettings,
    teacher: UserAccount,
) -> TeacherClassroom:
    classroom_id = _stable_id(settings, "classroom", teacher.role)
    classroom = session.get(TeacherClassroom, classroom_id)
    if classroom is None:
        classroom = session.scalar(
            select(TeacherClassroom).where(
                TeacherClassroom.teacher_user_account_id == teacher.id,
                TeacherClassroom.academic_year == 2027,
                TeacherClassroom.department_name == "합성 소프트웨어과",
                TeacherClassroom.class_name == "체험 3-A",
            )
        )
    if classroom is None:
        classroom = TeacherClassroom(
            id=classroom_id,
        )
        session.add(classroom)
    classroom.teacher_user_account_id = teacher.id
    classroom.academic_year = 2027
    classroom.department_name = "합성 소프트웨어과"
    classroom.class_name = "체험 3-A"
    session.flush()
    return classroom


def _upsert_classroom_student(
    session: Session,
    *,
    settings: DemoSandboxSettings,
    classroom: TeacherClassroom,
    key: str,
    anonymous_code: str,
    linked_account: UserAccount | None,
    occurred_at: datetime,
) -> ClassroomStudent:
    student_id = _stable_id(settings, "classroom-student", key)
    student = session.get(ClassroomStudent, student_id)
    if student is None:
        student = session.scalar(
            select(ClassroomStudent).where(
                ClassroomStudent.classroom_id == classroom.id,
                ClassroomStudent.anonymous_code == anonymous_code,
            )
        )
    if student is None:
        student = ClassroomStudent(
            id=student_id,
        )
        session.add(student)
    student.classroom_id = classroom.id
    student.anonymous_code = anonymous_code
    student.linked_user_account_id = None if linked_account is None else linked_account.id
    student.linked_at = None if linked_account is None else occurred_at
    student.link_code_digest = None
    student.link_code_hint = None
    student.link_code_expires_at = None
    session.flush()
    return student


def _seed_score_rows(
    session: Session,
    *,
    settings: DemoSandboxSettings,
    owner: UserAccount | None,
    managed_by: UserAccount | None,
    student_id: str,
    key: str,
) -> tuple[int, int]:
    if (owner is None) == (managed_by is None):
        raise DemoSandboxError("합성 성적은 학생 또는 교사 중 한 계정만 소유해야 합니다.")
    terms = tuple(
        dict.fromkeys((row.academic_year, row.grade, row.semester) for row in DEMO_SCORE_ROWS)
    )
    course_count = 0
    for term_index, (academic_year, grade, semester) in enumerate(terms, start=1):
        is_vocational_term = grade == 3 and semester == 1
        record_source = "VOCATIONAL_TRAINING_RECORD" if is_vocational_term else "HOME_SCHOOL_RECORD"
        record_id = _stable_id(settings, "academic-record", f"{key}:{term_index}")
        record = session.get(StudentAcademicRecord, record_id)
        if record is None:
            record = session.scalar(
                select(StudentAcademicRecord).where(
                    StudentAcademicRecord.student_id == student_id,
                    StudentAcademicRecord.academic_year == academic_year,
                    StudentAcademicRecord.grade == grade,
                    StudentAcademicRecord.semester == semester,
                    StudentAcademicRecord.record_source == record_source,
                )
            )
        if record is None:
            record = StudentAcademicRecord(
                id=record_id,
            )
            session.add(record)
        record.student_id = student_id
        record.academic_year = academic_year
        record.grade = grade
        record.semester = semester
        record.record_source = record_source
        record.owner_user_account_id = None if owner is None else owner.id
        record.managed_by_user_account_id = None if managed_by is None else managed_by.id
        record.original_school_id = None
        record.vocational_institution_name = "합성 직업교육기관" if is_vocational_term else None
        record.is_vocational_training_semester = is_vocational_term
        record.verification_status = "USER_VERIFIED"
        session.flush()

        term_rows = tuple(
            row
            for row in DEMO_SCORE_ROWS
            if (row.academic_year, row.grade, row.semester) == (academic_year, grade, semester)
        )
        for row_index, row in enumerate(term_rows, start=1):
            course_id = _stable_id(
                settings,
                "course-record",
                f"{key}:{term_index}:{row_index}",
            )
            course = session.get(StudentCourseRecord, course_id)
            if course is None:
                course = StudentCourseRecord(id=course_id, academic_record_id=record.id)
                session.add(course)
            course.academic_record_id = record.id
            course.subject_group = row.subject_group
            course.subject_name = row.subject_name
            course.credits = Decimal(row.credits)
            course.raw_score = Decimal(row.raw_score) if row.raw_score else None
            course.raw_score_label = None
            course.course_mean = Decimal(row.course_mean) if row.course_mean else None
            course.standard_deviation = (
                Decimal(row.standard_deviation) if row.standard_deviation else None
            )
            course.achievement_level = None
            course.enrollment_count = None
            course.rank_grade = Decimal(row.rank_grade)
            course.achievement_distribution = None
            course.source_page = None
            course.extraction_method = "DEMO_SYNTHETIC"
            course.extraction_confidence = None
            course.user_verified = True
            course_count += 1
    return len(terms), course_count


def _seed_outcomes(
    session: Session,
    *,
    settings: DemoSandboxSettings,
    teachers: tuple[UserAccount, ...],
) -> int:
    track = session.scalar(
        select(AdmissionTrack)
        .join(AdmissionRound, AdmissionRound.id == AdmissionTrack.admission_round_id)
        .join(Program, Program.id == AdmissionTrack.program_id)
        .join(Campus, Campus.id == Program.campus_id)
        .join(Institution, Institution.id == Campus.institution_id)
        .where(AdmissionRound.academic_year == 2027)
        .order_by(
            Institution.name,
            Campus.name,
            Program.name,
            AdmissionRound.name,
            AdmissionTrack.name,
            AdmissionTrack.id,
        )
        .limit(1)
    )
    if track is None:
        raise DemoSandboxError("Phase 17 공개 대학·학과·전형을 먼저 적재해야 합니다.")
    statuses = {
        "TEACHER": "INITIAL_ACCEPTED",
        "ADMIN": "UNKNOWN",
    }
    for teacher in teachers:
        student_code = f"SYNTH-{teacher.role[:3]}"
        outcome_id = _stable_id(settings, "institution-outcome", teacher.role)
        outcome = session.get(InstitutionApplicationOutcome, outcome_id)
        if outcome is None:
            outcome = session.scalar(
                select(InstitutionApplicationOutcome).where(
                    InstitutionApplicationOutcome.managed_by_user_account_id == teacher.id,
                    InstitutionApplicationOutcome.anonymous_student_code == student_code,
                    InstitutionApplicationOutcome.academic_year == 2027,
                    InstitutionApplicationOutcome.admission_track_id == track.id,
                )
            )
        if outcome is None:
            outcome = InstitutionApplicationOutcome(
                id=outcome_id,
            )
            session.add(outcome)
        outcome.managed_by_user_account_id = teacher.id
        outcome.anonymous_student_code = student_code
        outcome.academic_year = 2027
        outcome.admission_track_id = track.id
        outcome.reflected_grade = Decimal("2.77")
        outcome.outcome_status = statuses[teacher.role]
        outcome.initial_waitlist_number = None
        outcome.final_waitlist_number = None
        outcome.source_status = "UNCONFIRMED"
        outcome.notes = "실제 학생 자료가 아닌 체험 전용 합성 지원 결과"
    return len(teachers)


__all__ = [
    "DemoSandboxBootstrapResult",
    "DemoSandboxCredential",
    "DemoSandboxError",
    "DemoSandboxRoleSpec",
    "DemoSandboxSettings",
    "DemoSyntheticSeedResult",
    "active_demo_sandbox_credentials",
    "authenticate_demo_sandbox_gateway",
    "bootstrap_demo_sandbox",
    "demo_sandbox_mode_enabled",
    "purge_expired_demo_session_ai",
    "require_demo_sandbox_config",
    "register_demo_sandbox_cli",
    "reset_demo_role_accounts",
    "sandbox_role_specs",
    "seed_demo_synthetic_workspace",
]
