from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import ExternalIdentity, UserAccount, UserAccountAuditEvent, new_id

USER_ROLES = frozenset({"ADMIN", "ASSISTANT_ADMIN", "MEMBER"})
USER_STATUSES = frozenset({"PENDING_APPROVAL", "ACTIVE", "REJECTED", "SUSPENDED"})
CANONICAL_GOOGLE_ISSUER = "https://accounts.google.com"
GOOGLE_ISSUERS = frozenset({CANONICAL_GOOGLE_ISSUER, "accounts.google.com"})
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
DUMMY_PASSWORD_HASH = generate_password_hash("synthetic-non-account-password")
BOOTSTRAP_ADMIN_LOCK_KEY = 780_331_006_507_120_011
BOOTSTRAP_DEMO_LOCK_KEY = 780_331_006_507_120_012
DEMO_ACTOR_REF = "demo:public"
DEMO_EMAIL = "public-demo@local.invalid"


class MembershipError(RuntimeError):
    pass


class RegistrationConflict(MembershipError):
    """가입 가능 여부를 외부 응답에서 구분하면 안 되는 예약값 충돌."""


class DemoAccountConflict(MembershipError):
    """기존 계정을 덮어쓰지 않고 공개 데모만 비활성화해야 하는 충돌."""


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
            .where(UserAccount.role == "ADMIN", UserAccount.status == "ACTIVE")
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


def register_local_member(
    session: Session,
    *,
    login_name: str,
    email: str,
    display_name: str,
    password: str,
    occurred_at: datetime,
    requested_role: str | None = None,
    requested_status: str | None = None,
    reserved_login_name: str | None = None,
) -> UserAccount:
    del requested_role, requested_status
    _aware(occurred_at)
    _validate_password(password)
    normalized_login_name = _normalize_login_name(login_name)
    normalized_email = _normalize_email(email)
    if reserved_login_name and normalized_login_name == _normalize_login_name(reserved_login_name):
        raise RegistrationConflict("예약된 계정 정보입니다.")
    if normalized_email == DEMO_EMAIL:
        raise RegistrationConflict("예약된 계정 정보입니다.")
    account_id = new_id()
    member = UserAccount(
        id=account_id,
        actor_ref=f"user:{account_id}",
        login_name=normalized_login_name,
        email=normalized_email,
        display_name=_normalize_display_name(display_name),
        password_hash=generate_password_hash(password),
        role="MEMBER",
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
    try:
        normalized = _normalize_login_name(login_name)
    except MembershipError:
        check_password_hash(DUMMY_PASSWORD_HASH, password)
        return None
    member = session.scalar(select(UserAccount).where(UserAccount.login_name == normalized))
    if member is None or member.password_hash is None:
        check_password_hash(DUMMY_PASSWORD_HASH, password)
        return None
    if not check_password_hash(member.password_hash, password):
        return None
    if member.actor_ref == DEMO_ACTOR_REF:
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
        if existing.role != "ADMIN" or existing.status != "ACTIVE":
            raise MembershipError("동일 로그인 ID의 기존 회원을 관리자로 자동 승격할 수 없습니다.")
        if existing.password_hash != password_hash:
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
    occupied = session.scalar(select(UserAccount.id).where(UserAccount.email == canonical_email))
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
        or locked_actor.actor_ref == DEMO_ACTOR_REF
    ):
        raise MembershipError("회원 승인 권한이 없습니다.")
    locked = locked_accounts.get(target.id)
    if locked is None:
        raise MembershipError("승인 대상 회원을 찾을 수 없습니다.")
    if locked.id == locked_actor.id:
        raise MembershipError("자기 자신을 승인할 수 없습니다.")
    if locked.role != "MEMBER" or locked.status != "PENDING_APPROVAL":
        raise MembershipError("승인 대기 일반 회원만 승인할 수 있습니다.")
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
        or locked_actor.actor_ref == DEMO_ACTOR_REF
    ):
        raise MembershipError("회원 역할 변경 권한이 없습니다.")
    if new_role not in USER_ROLES:
        raise MembershipError("허용되지 않은 회원 역할입니다.")
    locked = locked_accounts.get(target.id)
    if locked is None:
        raise MembershipError("대상 회원을 찾을 수 없습니다.")
    if locked.actor_ref == DEMO_ACTOR_REF:
        raise MembershipError("공개 데모 계정의 역할은 변경할 수 없습니다.")
    if locked.status != "ACTIVE":
        raise MembershipError("활성 회원의 역할만 변경할 수 있습니다.")
    if locked.role == new_role:
        return locked
    if locked.role == "ADMIN" and new_role != "ADMIN" and len(active_admins) <= 1:
        raise MembershipError("마지막 활성 관리자는 강등할 수 없습니다.")
    before_role = locked.role
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
        or locked_actor.actor_ref == DEMO_ACTOR_REF
    ):
        raise MembershipError("회원 상태 변경 권한이 없습니다.")
    if new_status not in {"PENDING_APPROVAL", "REJECTED", "SUSPENDED", "ACTIVE"}:
        raise MembershipError("허용되지 않은 회원 상태입니다.")
    locked = locked_accounts.get(target.id)
    if locked is None:
        raise MembershipError("대상 회원을 찾을 수 없습니다.")
    if locked.actor_ref == DEMO_ACTOR_REF:
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
