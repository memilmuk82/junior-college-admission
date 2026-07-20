from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select, text
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import (
    ClassroomLinkAuditEvent,
    ClassroomStudent,
    ExternalIdentity,
    TeacherClassroom,
    UserAccount,
    UserAccountAuditEvent,
    new_id,
)

USER_ROLES = frozenset({"ADMIN", "ASSISTANT_ADMIN", "MEMBER", "STUDENT", "TEACHER"})
TEACHER_CAPABLE_ROLES = frozenset({"ADMIN", "TEACHER"})
USER_STATUSES = frozenset({"PENDING_APPROVAL", "ACTIVE", "REJECTED", "SUSPENDED"})
CANONICAL_GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_ISSUERS = frozenset({CANONICAL_GOOGLE_ISSUER, "accounts.google.com"})
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DUMMY_PASSWORD_HASH = generate_password_hash("synthetic-non-account-password")
BOOTSTRAP_ADMIN_LOCK_KEY = 780_331_006_507_120_011
BOOTSTRAP_DEMO_LOCK_KEY = 780_331_006_507_120_012
DEMO_ACTOR_REF = "demo:public"
DEMO_EMAIL = "public-demo@local.invalid"


@dataclass(frozen=True)
class DemoRoleSpec:
    role: str
    label: str
    login_name: str
    actor_ref: str
    email: str
    display_name: str


DEMO_ROLE_SPECS = (
    DemoRoleSpec(
        role="STUDENT",
        label="학생",
        login_name="demo-student",
        actor_ref="demo:role:STUDENT",
        email="public-demo-student@local.invalid",
        display_name="공개 데모 학생",
    ),
    DemoRoleSpec(
        role="TEACHER",
        label="교사",
        login_name="demo-teacher",
        actor_ref="demo:role:TEACHER",
        email="public-demo-teacher@local.invalid",
        display_name="공개 데모 교사",
    ),
    DemoRoleSpec(
        role="ADMIN",
        label="주 관리자",
        login_name="demo-main-admin",
        actor_ref="demo:role:ADMIN",
        email="public-demo-main-admin@local.invalid",
        display_name="공개 데모 주 관리자",
    ),
    DemoRoleSpec(
        role="ASSISTANT_ADMIN",
        label="보조 관리자",
        login_name="demo-assistant-admin",
        actor_ref="demo:role:ASSISTANT_ADMIN",
        email="public-demo-assistant-admin@local.invalid",
        display_name="공개 데모 보조 관리자",
    ),
)
DEMO_ROLE_ACTOR_REFS = {spec.role: spec.actor_ref for spec in DEMO_ROLE_SPECS}
DEMO_ROLE_LOGIN_NAMES = {spec.role: spec.login_name for spec in DEMO_ROLE_SPECS}
DEMO_ROLE_EMAILS = frozenset(spec.email for spec in DEMO_ROLE_SPECS)
DEMO_ROLE_LOGIN_NAME_SET = frozenset(spec.login_name for spec in DEMO_ROLE_SPECS)


@dataclass(frozen=True)
class DemoRoleCredential:
    role: str
    label: str
    login_name: str
    public_password: str


class MembershipError(RuntimeError):
    pass


class RegistrationConflict(MembershipError):
    """가입 가능 여부를 외부 응답에서 구분하면 안 되는 예약값 충돌."""


class DemoAccountConflict(MembershipError):
    """기존 계정을 덮어쓰지 않고 공개 데모만 비활성화해야 하는 충돌."""


def is_demo_actor_ref(value: str | None) -> bool:
    return value == DEMO_ACTOR_REF or (isinstance(value, str) and value.startswith("demo:role:"))


def role_has_teacher_capability(role: str) -> bool:
    """교사와 주 관리자만 교사 업무를 함께 수행한다."""
    return role in TEACHER_CAPABLE_ROLES


def has_teacher_capability(user: UserAccount) -> bool:
    """활성 교사 또는 주 관리자의 교사 기능을 판정한다."""
    return user.status == "ACTIVE" and role_has_teacher_capability(user.role)


def canonicalize_google_issuer(value: str) -> str:
    if value not in GOOGLE_ISSUERS:
        raise MembershipError("Google 발급자를 확인할 수 없습니다.")
    return CANONICAL_GOOGLE_ISSUER


def _aware(occurred_at: datetime) -> None:
    if occurred_at.tzinfo is None:
        raise MembershipError("처리 시각에는 시간대가 필요합니다.")


def _normalize_login_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    if len(normalized) < 4 or len(normalized) > 80 or any(char.isspace() for char in normalized):
        raise MembershipError("로그인 ID는 공백 없이 4~80자로 입력하세요.")
    return normalized


def _normalize_email(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    if len(normalized) > 320 or not EMAIL_PATTERN.fullmatch(normalized):
        raise MembershipError("이메일 형식을 확인하세요.")
    return normalized


def _normalize_display_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip()
    if not normalized or len(normalized) > 120:
        raise MembershipError("표시 이름은 1~120자로 입력하세요.")
    return normalized


def _validate_password(value: str) -> None:
    if len(value) < 12 or len(value) > 256:
        raise MembershipError("비밀번호는 12~256자로 입력하세요.")


def _audit(
    session: Session,
    *,
    target: UserAccount,
    actor: UserAccount | None,
    event_type: str,
    occurred_at: datetime,
    before_role: str | None = None,
    after_role: str | None = None,
    before_status: str | None = None,
    after_status: str | None = None,
) -> None:
    session.add(
        UserAccountAuditEvent(
            target_user_id=target.id,
            actor_user_id=None if actor is None else actor.id,
            event_type=event_type,
            before_role=before_role,
            after_role=after_role,
            before_status=before_status,
            after_status=after_status,
            occurred_at=occurred_at,
            details={},
        )
    )


def _lock_membership_mutation_accounts(
    session: Session,
    *,
    actor_id: str,
    target_id: str,
) -> tuple[dict[str, UserAccount], tuple[UserAccount, ...]]:
    """회원 권한 변경에 필요한 계정을 같은 순서로 최신 상태까지 잠근다."""
    active_admins = tuple(
        session.scalars(
            select(UserAccount)
            .where(
                UserAccount.role == "ADMIN",
                UserAccount.status == "ACTIVE",
                UserAccount.actor_ref != DEMO_ACTOR_REF,
                ~UserAccount.actor_ref.like("demo:role:%"),
            )
            .order_by(UserAccount.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    locked = {account.id: account for account in active_admins}
    missing_ids = sorted({actor_id, target_id}.difference(locked))
    if missing_ids:
        for account in session.scalars(
            select(UserAccount)
            .where(UserAccount.id.in_(missing_ids))
            .order_by(UserAccount.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        ):
            locked[account.id] = account
    return locked, active_admins


def _revoke_classroom_links(
    session: Session,
    *,
    target: UserAccount,
    actor: UserAccount,
    occurred_at: datetime,
    reason: str,
) -> None:
    students = tuple(
        session.scalars(
            select(ClassroomStudent)
            .join(TeacherClassroom, TeacherClassroom.id == ClassroomStudent.classroom_id)
            .where(
                or_(
                    TeacherClassroom.teacher_user_account_id == target.id,
                    ClassroomStudent.linked_user_account_id == target.id,
                )
            )
            .order_by(ClassroomStudent.id)
            .with_for_update()
        )
    )
    for student in students:
        was_linked = student.linked_user_account_id is not None
        had_pending_code = student.link_code_digest is not None
        if not was_linked and not had_pending_code:
            continue
        student.linked_user_account_id = None
        student.linked_at = None
        student.link_code_digest = None
        student.link_code_hint = None
        student.link_code_expires_at = None
        session.add(
            ClassroomLinkAuditEvent(
                classroom_student_id=student.id,
                actor_user_account_id=actor.id,
                event_type="STUDENT_UNLINKED" if was_linked else "LINK_CODE_REVOKED",
                occurred_at=occurred_at,
                details={"reason": reason},
            )
        )


def register_local_member(
    session: Session,
    *,
    login_name: str | None = None,
    email: str,
    display_name: str,
    password: str,
    occurred_at: datetime,
    requested_role: str | None = None,
    requested_status: str | None = None,
    reserved_login_name: str | None = None,
) -> UserAccount:
    del requested_status
    _aware(occurred_at)
    _validate_password(password)
    normalized_login_name = (
        _normalize_login_name(login_name) if login_name and login_name.strip() else None
    )
    normalized_email = _normalize_email(email)
    if normalized_login_name in DEMO_ROLE_LOGIN_NAME_SET or normalized_email in DEMO_ROLE_EMAILS:
        raise RegistrationConflict("예약된 계정 정보입니다.")
    if (
        normalized_login_name is not None
        and reserved_login_name
        and normalized_login_name == _normalize_login_name(reserved_login_name)
    ):
        raise RegistrationConflict("예약된 계정 정보입니다.")
    if normalized_email == DEMO_EMAIL:
        raise RegistrationConflict("예약된 계정 정보입니다.")
    password_hash = generate_password_hash(password)
    identity_conflicts = [
        UserAccount.email == normalized_email,
        UserAccount.login_name == normalized_email,
    ]
    if normalized_login_name is not None:
        identity_conflicts.extend(
            (
                UserAccount.login_name == normalized_login_name,
                UserAccount.email == normalized_login_name,
            )
        )
    if session.scalar(select(UserAccount.id).where(or_(*identity_conflicts))) is not None:
        raise RegistrationConflict("이미 사용 중인 계정 정보입니다.")
    account_id = new_id()
    role = requested_role if requested_role in {"STUDENT", "TEACHER"} else "MEMBER"
    member = UserAccount(
        id=account_id,
        actor_ref=f"user:{account_id}",
        login_name=normalized_login_name,
        email=normalized_email,
        display_name=_normalize_display_name(display_name),
        password_hash=password_hash,
        role=role,
        status="PENDING_APPROVAL",
        auth_version=1,
    )
    session.add(member)
    session.flush()
    _audit(
        session,
        target=member,
        actor=None,
        event_type="REGISTERED_LOCAL",
        occurred_at=occurred_at,
        after_role=member.role,
        after_status=member.status,
    )
    return member


def authenticate_local_member(
    session: Session,
    *,
    login_name: str,
    password: str,
    occurred_at: datetime,
) -> UserAccount | None:
    _aware(occurred_at)
    normalized_identifier = unicodedata.normalize("NFKC", login_name).strip().lower()
    identity_filters = []
    if "@" in normalized_identifier:
        try:
            normalized_email = _normalize_email(normalized_identifier)
        except MembershipError:
            pass
        else:
            identity_filters.append(
                and_(
                    UserAccount.email == normalized_email,
                    UserAccount.email_verified_at.is_not(None),
                )
            )
    try:
        normalized_login_name = _normalize_login_name(normalized_identifier)
    except MembershipError:
        pass
    else:
        identity_filters.append(UserAccount.login_name == normalized_login_name)
    if not identity_filters:
        check_password_hash(DUMMY_PASSWORD_HASH, password)
        return None
    matches = tuple(session.scalars(select(UserAccount).where(or_(*identity_filters)).limit(2)))
    if len(matches) != 1:
        check_password_hash(DUMMY_PASSWORD_HASH, password)
        return None
    member = matches[0]
    if member is None or member.password_hash is None:
        check_password_hash(DUMMY_PASSWORD_HASH, password)
        return None
    if not check_password_hash(member.password_hash, password):
        return None
    if is_demo_actor_ref(member.actor_ref):
        # 공개 공유 계정 로그인으로 감사 테이블이 무제한 증가하지 않게 한다.
        return member
    member.last_login_at = occurred_at
    _audit(
        session,
        target=member,
        actor=member,
        event_type="LOGIN_SUCCEEDED",
        occurred_at=occurred_at,
        after_role=member.role,
        after_status=member.status,
    )
    return member


def bootstrap_admin(
    session: Session,
    *,
    login_name: str,
    password_hash: str,
    occurred_at: datetime,
) -> UserAccount:
    _aware(occurred_at)
    normalized = _normalize_login_name(login_name)
    if normalized in DEMO_ROLE_LOGIN_NAME_SET or is_demo_actor_ref(normalized):
        raise MembershipError("공개 데모용 예약 로그인 ID는 관리자로 사용할 수 없습니다.")
    if not password_hash.strip():
        raise MembershipError("관리자 비밀번호 해시가 필요합니다.")
    # 여러 앱 replica가 동시에 시작해도 단 하나의 bootstrap 트랜잭션만
    # 존재 여부 확인과 INSERT를 수행하도록 PostgreSQL transaction lock을 쓴다.
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": BOOTSTRAP_ADMIN_LOCK_KEY},
    )
    existing = session.scalar(
        select(UserAccount)
        .where(UserAccount.login_name == normalized)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if existing is not None:
        if is_demo_actor_ref(existing.actor_ref):
            raise MembershipError("공개 데모 계정은 실제 관리자로 부트스트랩할 수 없습니다.")
        if existing.role != "ADMIN" or existing.status != "ACTIVE":
            raise MembershipError("동일 로그인 ID의 기존 회원을 관리자로 자동 승격할 수 없습니다.")
        if existing.bootstrap_password_managed and existing.password_hash != password_hash:
            existing.password_hash = password_hash
            existing.auth_version += 1
            _audit(
                session,
                target=existing,
                actor=existing,
                event_type="PASSWORD_CHANGED",
                occurred_at=occurred_at,
                after_role=existing.role,
                after_status=existing.status,
            )
        return existing

    account_id = new_id()
    local_digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    admin = UserAccount(
        id=account_id,
        # Phase 10까지 환경변수 관리자가 남긴 검수·AI 소유권과 동일한
        # 식별자를 유지한다. 이후 신규 계정은 UUID 기반 actor_ref를 쓴다.
        actor_ref=normalized,
        login_name=normalized,
        email=f"bootstrap-{local_digest}@local.invalid",
        display_name="시스템 관리자",
        password_hash=password_hash,
        role="ADMIN",
        status="ACTIVE",
        auth_version=1,
        bootstrap_password_managed=True,
        approved_by_user_id=account_id,
        approved_at=occurred_at,
    )
    session.add(admin)
    session.flush()
    _audit(
        session,
        target=admin,
        actor=admin,
        event_type="BOOTSTRAPPED_ADMIN",
        occurred_at=occurred_at,
        after_role=admin.role,
        after_status=admin.status,
    )
    return admin


def _suspend_demo_account(
    session: Session,
    *,
    account: UserAccount,
    actor: UserAccount | None,
    occurred_at: datetime,
    preserve_role: bool,
) -> bool:
    before_role = account.role
    before_status = account.status
    next_role = account.role if preserve_role else "MEMBER"
    if before_role == next_role and before_status == "SUSPENDED":
        return False
    account.role = next_role
    account.status = "SUSPENDED"
    if account.approved_by_user_id is None:
        account.approved_by_user_id = account.id if actor is None else actor.id
        account.approved_at = occurred_at
    account.password_hash = generate_password_hash(secrets.token_urlsafe(48))
    account.auth_version += 1
    if before_role != account.role:
        _audit(
            session,
            target=account,
            actor=actor,
            event_type="ROLE_CHANGED",
            occurred_at=occurred_at,
            before_role=before_role,
            after_role=account.role,
            before_status=before_status,
            after_status=account.status,
        )
    if before_status != account.status:
        _audit(
            session,
            target=account,
            actor=actor,
            event_type="STATUS_CHANGED",
            occurred_at=occurred_at,
            before_role=account.role,
            after_role=account.role,
            before_status=before_status,
            after_status=account.status,
        )
    _audit(
        session,
        target=account,
        actor=actor,
        event_type="PASSWORD_CHANGED",
        occurred_at=occurred_at,
        after_role=account.role,
        after_status=account.status,
    )
    return True


def bootstrap_demo_role_accounts(
    session: Session,
    *,
    public_password: str,
    approved_by: UserAccount,
    occurred_at: datetime,
) -> tuple[UserAccount, ...]:
    """네 역할의 공개 showcase 계정을 기존 계정 탈취 없이 멱등 생성한다."""

    _aware(occurred_at)
    _validate_password(public_password)
    if (
        approved_by.role != "ADMIN"
        or approved_by.status != "ACTIVE"
        or is_demo_actor_ref(approved_by.actor_ref)
    ):
        raise MembershipError("공개 데모 계정은 실제 활성 관리자만 부트스트랩할 수 있습니다.")
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": BOOTSTRAP_DEMO_LOCK_KEY},
    )
    actor_refs = tuple(spec.actor_ref for spec in DEMO_ROLE_SPECS)
    login_names = tuple(spec.login_name for spec in DEMO_ROLE_SPECS)
    emails = tuple(spec.email for spec in DEMO_ROLE_SPECS)
    matches = tuple(
        session.scalars(
            select(UserAccount)
            .where(
                or_(
                    UserAccount.actor_ref.in_((*actor_refs, DEMO_ACTOR_REF)),
                    UserAccount.login_name.in_(login_names),
                    UserAccount.email.in_(emails),
                )
            )
            .order_by(UserAccount.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )

    by_actor = {account.actor_ref: account for account in matches}
    by_login = {account.login_name: account for account in matches if account.login_name}
    by_email = {account.email: account for account in matches}
    legacy = by_actor.get(DEMO_ACTOR_REF)
    for spec in DEMO_ROLE_SPECS:
        existing = by_actor.get(spec.actor_ref)
        login_owner = by_login.get(spec.login_name)
        email_owner = by_email.get(spec.email)
        if (
            login_owner is not None and login_owner is not existing and login_owner is not legacy
        ) or (
            email_owner is not None and email_owner is not existing and email_owner is not legacy
        ):
            raise DemoAccountConflict("공개 역할 데모 계정 식별자가 이미 사용 중입니다.")

    if legacy is not None:
        reserved_login = legacy.login_name in login_names
        reserved_email = legacy.email in emails
        suspended = _suspend_demo_account(
            session,
            account=legacy,
            actor=approved_by,
            occurred_at=occurred_at,
            preserve_role=False,
        )
        if reserved_login:
            legacy.login_name = f"retired-demo-{legacy.id}"
        if reserved_email:
            legacy.email = f"retired-demo-{legacy.id}@local.invalid"
        if (reserved_login or reserved_email) and not suspended:
            legacy.password_hash = generate_password_hash(secrets.token_urlsafe(48))
            legacy.auth_version += 1
            _audit(
                session,
                target=legacy,
                actor=approved_by,
                event_type="PASSWORD_CHANGED",
                occurred_at=occurred_at,
                after_role=legacy.role,
                after_status=legacy.status,
            )
        session.flush()

    accounts: list[UserAccount] = []
    for spec in DEMO_ROLE_SPECS:
        existing = by_actor.get(spec.actor_ref)
        if existing is None:
            account_id = new_id()
            account = UserAccount(
                id=account_id,
                actor_ref=spec.actor_ref,
                login_name=spec.login_name,
                email=spec.email,
                display_name=spec.display_name,
                password_hash=generate_password_hash(public_password),
                role=spec.role,
                status="ACTIVE",
                auth_version=1,
                approved_by_user_id=account_id,
                approved_at=occurred_at,
            )
            session.add(account)
            session.flush()
            _audit(
                session,
                target=account,
                actor=None,
                event_type="REGISTERED_LOCAL",
                occurred_at=occurred_at,
                after_role=account.role,
                after_status="PENDING_APPROVAL",
            )
            _audit(
                session,
                target=account,
                actor=approved_by,
                event_type="APPROVED",
                occurred_at=occurred_at,
                before_role=account.role,
                after_role=account.role,
                before_status="PENDING_APPROVAL",
                after_status=account.status,
            )
            accounts.append(account)
            continue

        before_role = existing.role
        before_status = existing.status
        credentials_changed = (
            existing.login_name != spec.login_name
            or existing.email != spec.email
            or existing.display_name != spec.display_name
            or existing.password_hash is None
            or not check_password_hash(existing.password_hash, public_password)
        )
        changed = before_role != spec.role or before_status != "ACTIVE" or credentials_changed
        existing.login_name = spec.login_name
        existing.email = spec.email
        existing.display_name = spec.display_name
        existing.role = spec.role
        existing.status = "ACTIVE"
        existing.approved_by_user_id = existing.id
        if existing.approved_at is None:
            existing.approved_at = occurred_at
        if credentials_changed:
            existing.password_hash = generate_password_hash(public_password)
        if changed:
            existing.auth_version += 1
        if before_role != existing.role:
            _audit(
                session,
                target=existing,
                actor=approved_by,
                event_type="ROLE_CHANGED",
                occurred_at=occurred_at,
                before_role=before_role,
                after_role=existing.role,
                before_status=before_status,
                after_status=existing.status,
            )
        if before_status != existing.status:
            _audit(
                session,
                target=existing,
                actor=approved_by,
                event_type="STATUS_CHANGED",
                occurred_at=occurred_at,
                before_role=existing.role,
                after_role=existing.role,
                before_status=before_status,
                after_status=existing.status,
            )
        if credentials_changed:
            _audit(
                session,
                target=existing,
                actor=approved_by,
                event_type="PASSWORD_CHANGED",
                occurred_at=occurred_at,
                after_role=existing.role,
                after_status=existing.status,
            )
        accounts.append(existing)

    return tuple(accounts)


def revoke_demo_role_accounts(
    session: Session,
    *,
    occurred_at: datetime,
) -> tuple[UserAccount, ...]:
    """알려진 비밀번호를 폐기하고 역할 데모의 기존 세션을 무효화한다."""

    _aware(occurred_at)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": BOOTSTRAP_DEMO_LOCK_KEY},
    )
    accounts = tuple(
        session.scalars(
            select(UserAccount)
            .where(UserAccount.actor_ref.in_(tuple(DEMO_ROLE_ACTOR_REFS.values())))
            .order_by(UserAccount.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    for account in accounts:
        _suspend_demo_account(
            session,
            account=account,
            actor=None,
            occurred_at=occurred_at,
            preserve_role=True,
        )
    return accounts


def active_demo_role_credentials(
    session: Session,
    *,
    public_password: object,
) -> tuple[DemoRoleCredential, ...] | None:
    """DB의 네 활성 showcase 계정과 공통 비밀번호가 모두 일치할 때만 표시한다."""

    if not isinstance(public_password, str):
        return None
    try:
        _validate_password(public_password)
    except MembershipError:
        return None
    accounts = tuple(
        session.scalars(
            select(UserAccount).where(
                UserAccount.actor_ref.in_(tuple(DEMO_ROLE_ACTOR_REFS.values()))
            )
        )
    )
    by_actor = {account.actor_ref: account for account in accounts}
    credentials: list[DemoRoleCredential] = []
    for spec in DEMO_ROLE_SPECS:
        account = by_actor.get(spec.actor_ref)
        if (
            account is None
            or account.login_name != spec.login_name
            or account.email != spec.email
            or account.role != spec.role
            or account.status != "ACTIVE"
            or account.password_hash is None
            or not check_password_hash(account.password_hash, public_password)
        ):
            return None
        credentials.append(
            DemoRoleCredential(
                role=spec.role,
                label=spec.label,
                login_name=spec.login_name,
                public_password=public_password,
            )
        )
    return tuple(credentials)


def bootstrap_demo_member(
    session: Session,
    *,
    login_name: str,
    public_password: str,
    approved_by: UserAccount,
    occurred_at: datetime,
) -> UserAccount:
    """공개 포트폴리오 체험용 최소권한 MEMBER를 멱등 생성한다."""
    _aware(occurred_at)
    normalized = _normalize_login_name(login_name)
    _validate_password(public_password)
    if approved_by.role != "ADMIN" or approved_by.status != "ACTIVE":
        raise MembershipError("공개 데모 계정은 활성 관리자만 부트스트랩할 수 있습니다.")
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": BOOTSTRAP_DEMO_LOCK_KEY},
    )
    matches = tuple(
        session.scalars(
            select(UserAccount)
            .where(
                (UserAccount.actor_ref == DEMO_ACTOR_REF)
                | (UserAccount.login_name == normalized)
                | (UserAccount.email == DEMO_EMAIL)
            )
            .order_by(UserAccount.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    existing = next((account for account in matches if account.actor_ref == DEMO_ACTOR_REF), None)
    login_owner = next((account for account in matches if account.login_name == normalized), None)
    email_owner = next((account for account in matches if account.email == DEMO_EMAIL), None)
    if existing is not None:
        if login_owner is not None and login_owner.id != existing.id:
            raise DemoAccountConflict("공개 데모 계정 식별자가 이미 사용 중입니다.")
        if email_owner is not None and email_owner.id != existing.id:
            raise DemoAccountConflict("공개 데모 계정 식별자가 이미 사용 중입니다.")
        before_role = existing.role
        before_status = existing.status
        credentials_changed = (
            existing.login_name != normalized
            or existing.email != DEMO_EMAIL
            or existing.password_hash is None
        )
        if existing.password_hash is not None and not check_password_hash(
            existing.password_hash, public_password
        ):
            credentials_changed = True
        changed = before_role != "MEMBER" or before_status != "ACTIVE" or credentials_changed
        existing.login_name = normalized
        existing.email = DEMO_EMAIL
        existing.role = "MEMBER"
        existing.status = "ACTIVE"
        existing.approved_by_user_id = approved_by.id
        if existing.approved_at is None:
            existing.approved_at = occurred_at
        if credentials_changed:
            existing.password_hash = generate_password_hash(public_password)
        if changed:
            existing.auth_version += 1
        if before_role != existing.role:
            _audit(
                session,
                target=existing,
                actor=approved_by,
                event_type="ROLE_CHANGED",
                occurred_at=occurred_at,
                before_role=before_role,
                after_role=existing.role,
                before_status=before_status,
                after_status=existing.status,
            )
        if before_status != existing.status:
            _audit(
                session,
                target=existing,
                actor=approved_by,
                event_type="STATUS_CHANGED",
                occurred_at=occurred_at,
                before_role=existing.role,
                after_role=existing.role,
                before_status=before_status,
                after_status=existing.status,
            )
        if credentials_changed:
            _audit(
                session,
                target=existing,
                actor=approved_by,
                event_type="PASSWORD_CHANGED",
                occurred_at=occurred_at,
                after_role=existing.role,
                after_status=existing.status,
            )
        return existing
    if login_owner is not None or email_owner is not None:
        raise DemoAccountConflict("공개 데모 계정 식별자가 이미 사용 중입니다.")

    account_id = new_id()
    demo = UserAccount(
        id=account_id,
        actor_ref=DEMO_ACTOR_REF,
        login_name=normalized,
        email=DEMO_EMAIL,
        display_name="공개 데모 교사",
        password_hash=generate_password_hash(public_password),
        role="MEMBER",
        status="ACTIVE",
        auth_version=1,
        approved_by_user_id=approved_by.id,
        approved_at=occurred_at,
    )
    session.add(demo)
    session.flush()
    _audit(
        session,
        target=demo,
        actor=None,
        event_type="REGISTERED_LOCAL",
        occurred_at=occurred_at,
        after_role=demo.role,
        after_status="PENDING_APPROVAL",
    )
    _audit(
        session,
        target=demo,
        actor=approved_by,
        event_type="APPROVED",
        occurred_at=occurred_at,
        before_role=demo.role,
        after_role=demo.role,
        before_status="PENDING_APPROVAL",
        after_status=demo.status,
    )
    return demo


def revoke_demo_member(
    session: Session,
    *,
    occurred_at: datetime,
) -> UserAccount | None:
    """비활성 공개 데모 계정의 세션과 알려진 자격증명을 폐기한다."""
    _aware(occurred_at)
    session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_key)"),
        {"lock_key": BOOTSTRAP_DEMO_LOCK_KEY},
    )
    existing = session.scalar(
        select(UserAccount)
        .where(UserAccount.actor_ref == DEMO_ACTOR_REF)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if existing is None:
        return None
    if existing.role == "MEMBER" and existing.status == "SUSPENDED":
        return existing

    before_role = existing.role
    before_status = existing.status
    existing.role = "MEMBER"
    existing.status = "SUSPENDED"
    if existing.approved_by_user_id is None:
        existing.approved_by_user_id = existing.id
        existing.approved_at = occurred_at
    existing.password_hash = generate_password_hash(secrets.token_urlsafe(48))
    existing.auth_version += 1
    if before_role != existing.role:
        _audit(
            session,
            target=existing,
            actor=None,
            event_type="ROLE_CHANGED",
            occurred_at=occurred_at,
            before_role=before_role,
            after_role=existing.role,
            before_status=before_status,
            after_status=existing.status,
        )
    if before_status != existing.status:
        _audit(
            session,
            target=existing,
            actor=None,
            event_type="STATUS_CHANGED",
            occurred_at=occurred_at,
            before_role=existing.role,
            after_role=existing.role,
            before_status=before_status,
            after_status=existing.status,
        )
    _audit(
        session,
        target=existing,
        actor=None,
        event_type="PASSWORD_CHANGED",
        occurred_at=occurred_at,
        after_role=existing.role,
        after_status=existing.status,
    )
    return existing


def active_demo_credentials(
    session: Session,
    *,
    login_name: object,
    public_password: object,
) -> tuple[str, str] | None:
    """현재 DB의 활성 최소권한 데모와 일치할 때만 공개 자격증명을 반환한다."""
    if not isinstance(login_name, str) or not isinstance(public_password, str):
        return None
    try:
        normalized = _normalize_login_name(login_name)
        _validate_password(public_password)
    except MembershipError:
        return None
    demo = session.scalar(select(UserAccount).where(UserAccount.actor_ref == DEMO_ACTOR_REF))
    if (
        demo is None
        or demo.login_name != normalized
        or demo.email != DEMO_EMAIL
        or demo.role != "MEMBER"
        or demo.status != "ACTIVE"
        or demo.password_hash is None
        or not check_password_hash(demo.password_hash, public_password)
    ):
        return None
    return normalized, public_password


def register_google_member(
    session: Session,
    *,
    issuer: str,
    subject: str,
    email: str,
    email_verified: bool,
    display_name: str,
    occurred_at: datetime,
) -> UserAccount:
    _aware(occurred_at)
    canonical_issuer = canonicalize_google_issuer(issuer.strip())
    canonical_subject = subject.strip()
    if not canonical_subject or len(canonical_subject) > 255:
        raise MembershipError("Google 사용자 식별자를 확인할 수 없습니다.")
    if email_verified is not True:
        raise MembershipError("검증된 Google 이메일만 사용할 수 있습니다.")

    identity = session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.provider == "GOOGLE",
            ExternalIdentity.issuer == canonical_issuer,
            ExternalIdentity.provider_subject == canonical_subject,
        )
    )
    if identity is not None:
        member = session.get(UserAccount, identity.user_account_id)
        if member is None:
            raise MembershipError("Google 계정 연결 상태를 확인할 수 없습니다.")
        member.last_login_at = occurred_at
        _audit(
            session,
            target=member,
            actor=member,
            event_type="LOGIN_SUCCEEDED",
            occurred_at=occurred_at,
            after_role=member.role,
            after_status=member.status,
        )
        return member

    canonical_email = _normalize_email(email)
    occupied = session.scalar(
        select(UserAccount.id).where(
            or_(
                UserAccount.email == canonical_email,
                UserAccount.login_name == canonical_email,
            )
        )
    )
    if occupied is not None:
        raise MembershipError("동일 이메일 계정은 관리자 확인 없이 자동 연결하지 않습니다.")

    account_id = new_id()
    member = UserAccount(
        id=account_id,
        actor_ref=f"user:{account_id}",
        login_name=None,
        email=canonical_email,
        display_name=_normalize_display_name(display_name),
        password_hash=None,
        role="MEMBER",
        status="PENDING_APPROVAL",
        auth_version=1,
        email_verified_at=occurred_at,
    )
    session.add(member)
    session.flush()
    session.add(
        ExternalIdentity(
            user_account_id=member.id,
            provider="GOOGLE",
            issuer=canonical_issuer,
            provider_subject=canonical_subject,
        )
    )
    _audit(
        session,
        target=member,
        actor=None,
        event_type="REGISTERED_GOOGLE",
        occurred_at=occurred_at,
        after_role=member.role,
        after_status=member.status,
    )
    return member


def approve_pending_member(
    session: Session,
    *,
    actor: UserAccount,
    target: UserAccount,
    occurred_at: datetime,
) -> UserAccount:
    _aware(occurred_at)
    locked_accounts, _active_admins = _lock_membership_mutation_accounts(
        session,
        actor_id=actor.id,
        target_id=target.id,
    )
    locked_actor = locked_accounts.get(actor.id)
    if (
        locked_actor is None
        or locked_actor.status != "ACTIVE"
        or locked_actor.role not in {"ADMIN", "ASSISTANT_ADMIN"}
        or is_demo_actor_ref(locked_actor.actor_ref)
    ):
        raise MembershipError("회원 승인 권한이 없습니다.")
    locked = locked_accounts.get(target.id)
    if locked is None:
        raise MembershipError("승인 대상 회원을 찾을 수 없습니다.")
    if is_demo_actor_ref(locked.actor_ref):
        raise MembershipError("공개 데모 계정은 승인할 수 없습니다.")
    if locked.id == locked_actor.id:
        raise MembershipError("자기 자신을 승인할 수 없습니다.")
    if locked.role not in {"MEMBER", "STUDENT", "TEACHER"} or locked.status != "PENDING_APPROVAL":
        raise MembershipError("승인 대기 일반 회원·학생·교사만 승인할 수 있습니다.")
    if locked.login_name is None and locked.email_verified_at is None:
        raise MembershipError("이메일 인증을 완료한 회원만 승인할 수 있습니다.")
    before_status = locked.status
    locked.status = "ACTIVE"
    locked.approved_by_user_id = locked_actor.id
    locked.approved_at = occurred_at
    locked.auth_version += 1
    _audit(
        session,
        target=locked,
        actor=locked_actor,
        event_type="APPROVED",
        occurred_at=occurred_at,
        before_role=locked.role,
        after_role=locked.role,
        before_status=before_status,
        after_status=locked.status,
    )
    return locked


def change_member_role(
    session: Session,
    *,
    actor: UserAccount,
    target: UserAccount,
    new_role: str,
    occurred_at: datetime,
) -> UserAccount:
    _aware(occurred_at)
    locked_accounts, active_admins = _lock_membership_mutation_accounts(
        session,
        actor_id=actor.id,
        target_id=target.id,
    )
    locked_actor = locked_accounts.get(actor.id)
    if (
        locked_actor is None
        or locked_actor.status != "ACTIVE"
        or locked_actor.role != "ADMIN"
        or is_demo_actor_ref(locked_actor.actor_ref)
    ):
        raise MembershipError("회원 역할 변경 권한이 없습니다.")
    if new_role not in USER_ROLES:
        raise MembershipError("허용되지 않은 회원 역할입니다.")
    locked = locked_accounts.get(target.id)
    if locked is None:
        raise MembershipError("대상 회원을 찾을 수 없습니다.")
    if is_demo_actor_ref(locked.actor_ref):
        raise MembershipError("공개 데모 계정의 역할은 변경할 수 없습니다.")
    if locked.status != "ACTIVE":
        raise MembershipError("활성 회원의 역할만 변경할 수 있습니다.")
    if locked.role == new_role:
        return locked
    if locked.role == "ADMIN" and new_role != "ADMIN" and len(active_admins) <= 1:
        raise MembershipError("마지막 활성 관리자는 강등할 수 없습니다.")
    before_role = locked.role
    if not (role_has_teacher_capability(locked.role) and role_has_teacher_capability(new_role)):
        _revoke_classroom_links(
            session,
            target=locked,
            actor=locked_actor,
            occurred_at=occurred_at,
            reason="ACCOUNT_ROLE_CHANGED",
        )
    locked.role = new_role
    locked.auth_version += 1
    _audit(
        session,
        target=locked,
        actor=locked_actor,
        event_type="ROLE_CHANGED",
        occurred_at=occurred_at,
        before_role=before_role,
        after_role=locked.role,
        before_status=locked.status,
        after_status=locked.status,
    )
    return locked


def change_member_status(
    session: Session,
    *,
    actor: UserAccount,
    target: UserAccount,
    new_status: str,
    occurred_at: datetime,
) -> UserAccount:
    _aware(occurred_at)
    locked_accounts, active_admins = _lock_membership_mutation_accounts(
        session,
        actor_id=actor.id,
        target_id=target.id,
    )
    locked_actor = locked_accounts.get(actor.id)
    if (
        locked_actor is None
        or locked_actor.status != "ACTIVE"
        or locked_actor.role != "ADMIN"
        or is_demo_actor_ref(locked_actor.actor_ref)
    ):
        raise MembershipError("회원 상태 변경 권한이 없습니다.")
    if new_status not in {"PENDING_APPROVAL", "REJECTED", "SUSPENDED", "ACTIVE"}:
        raise MembershipError("허용되지 않은 회원 상태입니다.")
    locked = locked_accounts.get(target.id)
    if locked is None:
        raise MembershipError("대상 회원을 찾을 수 없습니다.")
    if is_demo_actor_ref(locked.actor_ref):
        raise MembershipError("공개 데모 계정의 상태는 변경할 수 없습니다.")
    if locked.role == "ADMIN" and new_status != "ACTIVE" and len(active_admins) <= 1:
        raise MembershipError("마지막 활성 관리자는 정지할 수 없습니다.")
    allowed = {
        ("PENDING_APPROVAL", "REJECTED"),
        ("REJECTED", "PENDING_APPROVAL"),
        ("ACTIVE", "SUSPENDED"),
        ("SUSPENDED", "ACTIVE"),
    }
    if (locked.status, new_status) not in allowed:
        raise MembershipError("현재 상태에서 요청한 회원 상태로 변경할 수 없습니다.")
    before_status = locked.status
    if before_status == "ACTIVE" and new_status != "ACTIVE":
        _revoke_classroom_links(
            session,
            target=locked,
            actor=locked_actor,
            occurred_at=occurred_at,
            reason="ACCOUNT_STATUS_CHANGED",
        )
    locked.status = new_status
    if new_status in {"PENDING_APPROVAL", "REJECTED"}:
        locked.approved_by_user_id = None
        locked.approved_at = None
    locked.auth_version += 1
    _audit(
        session,
        target=locked,
        actor=locked_actor,
        event_type="STATUS_CHANGED",
        occurred_at=occurred_at,
        before_role=locked.role,
        after_role=locked.role,
        before_status=before_status,
        after_status=locked.status,
    )
    return locked
