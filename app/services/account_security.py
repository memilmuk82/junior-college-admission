from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash, generate_password_hash

from app.models import (
    AccountAuthToken,
    ExternalIdentity,
    UserAccount,
    UserAccountAuditEvent,
)
from app.services.membership import (
    CANONICAL_GOOGLE_ISSUER,
    MembershipError,
    _aware,
    _normalize_email,
    _validate_password,
    canonicalize_google_issuer,
    is_demo_actor_ref,
)

EMAIL_VERIFICATION = "EMAIL_VERIFICATION"
PASSWORD_RESET = "PASSWORD_RESET"
ACCOUNT_TOKEN_PURPOSES = frozenset({EMAIL_VERIFICATION, PASSWORD_RESET})
EMAIL_VERIFICATION_TTL = timedelta(hours=24)
PASSWORD_RESET_TTL = timedelta(minutes=30)


def _raw_token_digest(token: str) -> str | None:
    if not isinstance(token, str) or len(token) < 20 or len(token) > 512:
        return None
    if token != token.strip() or any(character.isspace() for character in token):
        return None
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _new_token() -> tuple[str, str]:
    raw = secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _resolve_expiry(
    *, occurred_at: datetime, expires_at: datetime | None, default_ttl: timedelta
) -> datetime:
    resolved = occurred_at + default_ttl if expires_at is None else expires_at
    _aware(resolved)
    if resolved <= occurred_at:
        raise MembershipError("인증 링크 만료 시각을 확인하세요.")
    return resolved


def _locked_user(session: Session, user_id: str) -> UserAccount:
    user = session.scalar(
        select(UserAccount)
        .where(UserAccount.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise MembershipError("계정 정보를 확인할 수 없습니다.")
    return user


def _require_mutable_user(user: UserAccount, *, active: bool = False) -> None:
    if is_demo_actor_ref(user.actor_ref):
        raise MembershipError("공개 데모 계정의 보안 정보는 변경할 수 없습니다.")
    if active and user.status != "ACTIVE":
        raise MembershipError("활성 계정에서만 요청할 수 있습니다.")


def _audit(
    session: Session,
    *,
    user: UserAccount,
    event_type: str,
    occurred_at: datetime,
) -> None:
    session.add(
        UserAccountAuditEvent(
            target_user_id=user.id,
            actor_user_id=user.id,
            event_type=event_type,
            before_role=user.role,
            after_role=user.role,
            before_status=user.status,
            after_status=user.status,
            occurred_at=occurred_at,
            details={},
        )
    )


def _revoke_open_tokens(
    session: Session,
    *,
    user_id: str,
    occurred_at: datetime,
    purpose: str | None = None,
    excluding_id: str | None = None,
) -> None:
    statement = (
        select(AccountAuthToken)
        .where(
            AccountAuthToken.user_account_id == user_id,
            AccountAuthToken.consumed_at.is_(None),
            AccountAuthToken.revoked_at.is_(None),
        )
        .order_by(AccountAuthToken.id)
        .with_for_update()
    )
    if purpose is not None:
        statement = statement.where(AccountAuthToken.purpose == purpose)
    if excluding_id is not None:
        statement = statement.where(AccountAuthToken.id != excluding_id)
    for token in session.scalars(statement):
        token.revoked_at = occurred_at


def _locked_usable_token(
    session: Session,
    *,
    raw_token: str,
    purpose: str,
    occurred_at: datetime,
) -> tuple[AccountAuthToken, UserAccount]:
    digest = _raw_token_digest(raw_token)
    if digest is None:
        raise MembershipError("인증 링크가 유효하지 않거나 만료되었습니다.")

    # 발급 경로도 user row를 먼저 잠근 뒤 token을 잠근다. 소비 경로 역시
    # 같은 lock 순서를 유지해 재발급과 동시 소비 사이의 교착을 피한다.
    candidate = session.scalar(
        select(AccountAuthToken).where(
            AccountAuthToken.token_digest == digest,
            AccountAuthToken.purpose == purpose,
        )
    )
    if candidate is None:
        raise MembershipError("인증 링크가 유효하지 않거나 만료되었습니다.")
    user = _locked_user(session, candidate.user_account_id)
    token = session.scalar(
        select(AccountAuthToken)
        .where(
            AccountAuthToken.id == candidate.id,
            AccountAuthToken.token_digest == digest,
            AccountAuthToken.purpose == purpose,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        token is None
        or token.consumed_at is not None
        or token.revoked_at is not None
        or token.expires_at <= occurred_at
        or token.issued_auth_version != user.auth_version
    ):
        raise MembershipError("인증 링크가 유효하지 않거나 만료되었습니다.")
    return token, user


def account_token_is_usable(
    session: Session,
    *,
    raw_token: str,
    purpose: str,
    occurred_at: datetime,
) -> bool:
    """GET 확인 화면에서 token을 소비하지 않고 상태만 확인한다."""

    _aware(occurred_at)
    if purpose not in ACCOUNT_TOKEN_PURPOSES:
        return False
    digest = _raw_token_digest(raw_token)
    if digest is None:
        return False
    return (
        session.scalar(
            select(AccountAuthToken.id)
            .join(UserAccount, UserAccount.id == AccountAuthToken.user_account_id)
            .where(
                AccountAuthToken.token_digest == digest,
                AccountAuthToken.purpose == purpose,
                AccountAuthToken.consumed_at.is_(None),
                AccountAuthToken.revoked_at.is_(None),
                AccountAuthToken.expires_at > occurred_at,
                AccountAuthToken.issued_auth_version == UserAccount.auth_version,
            )
        )
        is not None
    )


def issue_email_verification_token(
    session: Session,
    *,
    user: UserAccount,
    target_email: str,
    occurred_at: datetime,
    expires_at: datetime | None = None,
) -> str:
    _aware(occurred_at)
    normalized_email = _normalize_email(target_email)
    resolved_expiry = _resolve_expiry(
        occurred_at=occurred_at,
        expires_at=expires_at,
        default_ttl=EMAIL_VERIFICATION_TTL,
    )
    locked = _locked_user(session, user.id)
    _require_mutable_user(locked)
    email_owner = session.scalar(
        select(UserAccount.id).where(
            UserAccount.id != locked.id,
            or_(
                UserAccount.email == normalized_email,
                UserAccount.login_name == normalized_email,
            ),
        )
    )
    if email_owner is not None:
        raise MembershipError("이미 사용 중인 이메일입니다.")

    raw, digest = _new_token()
    session.add(
        AccountAuthToken(
            user_account_id=locked.id,
            purpose=EMAIL_VERIFICATION,
            token_digest=digest,
            issued_auth_version=locked.auth_version,
            target_email=normalized_email,
            expires_at=resolved_expiry,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
    )
    _audit(
        session,
        user=locked,
        event_type="EMAIL_VERIFICATION_REQUESTED",
        occurred_at=occurred_at,
    )
    return raw


def verify_email_token(
    session: Session,
    *,
    raw_token: str,
    occurred_at: datetime,
) -> UserAccount:
    _aware(occurred_at)
    stored, user = _locked_usable_token(
        session,
        raw_token=raw_token,
        purpose=EMAIL_VERIFICATION,
        occurred_at=occurred_at,
    )
    _require_mutable_user(user)
    email_owner = session.scalar(
        select(UserAccount.id).where(
            UserAccount.id != user.id,
            or_(
                UserAccount.email == stored.target_email,
                UserAccount.login_name == stored.target_email,
            ),
        )
    )
    if email_owner is not None:
        raise MembershipError("이미 사용 중인 이메일입니다.")

    email_changed = user.email != stored.target_email
    user.email = stored.target_email
    user.email_verified_at = occurred_at
    user.auth_version += 1
    stored.consumed_at = occurred_at
    _revoke_open_tokens(
        session,
        user_id=user.id,
        occurred_at=occurred_at,
        excluding_id=stored.id,
    )
    if email_changed:
        _audit(session, user=user, event_type="EMAIL_CHANGED", occurred_at=occurred_at)
    _audit(session, user=user, event_type="EMAIL_VERIFIED", occurred_at=occurred_at)
    return user


def issue_password_reset_token(
    session: Session,
    *,
    email: str,
    occurred_at: datetime,
    expires_at: datetime | None = None,
) -> tuple[UserAccount, str] | None:
    _aware(occurred_at)
    try:
        normalized_email = _normalize_email(email)
    except MembershipError:
        secrets.token_urlsafe(32)
        return None
    user_id = session.scalar(
        select(UserAccount.id).where(
            UserAccount.email == normalized_email,
            UserAccount.email_verified_at.is_not(None),
            UserAccount.password_hash.is_not(None),
            UserAccount.status.in_(("PENDING_APPROVAL", "ACTIVE")),
        )
    )
    if user_id is None:
        secrets.token_urlsafe(32)
        return None
    user = _locked_user(session, user_id)
    # The account may change while the first lookup waits for this row lock.
    # Recheck every eligibility predicate on the locked row so a concurrent
    # suspension, email change, or password removal cannot issue a fresh token.
    if (
        is_demo_actor_ref(user.actor_ref)
        or user.email != normalized_email
        or user.email_verified_at is None
        or user.password_hash is None
        or user.status not in {"PENDING_APPROVAL", "ACTIVE"}
    ):
        secrets.token_urlsafe(32)
        return None
    resolved_expiry = _resolve_expiry(
        occurred_at=occurred_at,
        expires_at=expires_at,
        default_ttl=PASSWORD_RESET_TTL,
    )
    raw, digest = _new_token()
    session.add(
        AccountAuthToken(
            user_account_id=user.id,
            purpose=PASSWORD_RESET,
            token_digest=digest,
            issued_auth_version=user.auth_version,
            target_email=user.email,
            expires_at=resolved_expiry,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
    )
    _audit(
        session,
        user=user,
        event_type="PASSWORD_RESET_REQUESTED",
        occurred_at=occurred_at,
    )
    return user, raw


def reset_password_with_token(
    session: Session,
    *,
    raw_token: str,
    new_password: str,
    occurred_at: datetime,
) -> UserAccount:
    _aware(occurred_at)
    _validate_password(new_password)
    stored, user = _locked_usable_token(
        session,
        raw_token=raw_token,
        purpose=PASSWORD_RESET,
        occurred_at=occurred_at,
    )
    _require_mutable_user(user)
    if user.email_verified_at is None or user.email != stored.target_email:
        raise MembershipError("인증 링크가 유효하지 않거나 만료되었습니다.")
    user.password_hash = generate_password_hash(new_password)
    user.bootstrap_password_managed = False
    user.auth_version += 1
    stored.consumed_at = occurred_at
    _revoke_open_tokens(
        session,
        user_id=user.id,
        occurred_at=occurred_at,
        excluding_id=stored.id,
    )
    _audit(
        session,
        user=user,
        event_type="PASSWORD_RESET_COMPLETED",
        occurred_at=occurred_at,
    )
    return user


def change_password(
    session: Session,
    *,
    user: UserAccount,
    current_password: str,
    new_password: str,
    occurred_at: datetime,
) -> UserAccount:
    _aware(occurred_at)
    _validate_password(new_password)
    locked = _locked_user(session, user.id)
    _require_mutable_user(locked, active=True)
    if locked.password_hash is None or not check_password_hash(
        locked.password_hash, current_password
    ):
        raise MembershipError("현재 비밀번호를 확인하세요.")
    locked.password_hash = generate_password_hash(new_password)
    locked.bootstrap_password_managed = False
    locked.auth_version += 1
    _revoke_open_tokens(
        session,
        user_id=locked.id,
        occurred_at=occurred_at,
    )
    _audit(session, user=locked, event_type="PASSWORD_CHANGED", occurred_at=occurred_at)
    return locked


def google_identity_for_user(session: Session, *, user: UserAccount) -> ExternalIdentity | None:
    return session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.user_account_id == user.id,
            ExternalIdentity.provider == "GOOGLE",
        )
    )


def connect_google_identity(
    session: Session,
    *,
    user: UserAccount,
    issuer: str,
    subject: str,
    email: str,
    email_verified: bool,
    occurred_at: datetime,
) -> ExternalIdentity:
    _aware(occurred_at)
    canonical_issuer = canonicalize_google_issuer(issuer.strip())
    canonical_subject = subject.strip()
    if not canonical_subject or len(canonical_subject) > 255:
        raise MembershipError("Google 사용자 식별자를 확인할 수 없습니다.")
    if email_verified is not True:
        raise MembershipError("검증된 Google 이메일만 연결할 수 있습니다.")
    canonical_email = _normalize_email(email)
    locked = _locked_user(session, user.id)
    _require_mutable_user(locked, active=True)
    if locked.password_hash is None:
        raise MembershipError("로컬 비밀번호 계정에서만 Google 계정을 연결할 수 있습니다.")
    if canonical_email != locked.email:
        raise MembershipError("계정 이메일과 같은 Google 이메일만 연결할 수 있습니다.")

    current_identity = session.scalar(
        select(ExternalIdentity)
        .where(
            ExternalIdentity.user_account_id == locked.id,
            ExternalIdentity.provider == "GOOGLE",
        )
        .with_for_update()
    )
    subject_owner = session.scalar(
        select(ExternalIdentity)
        .where(
            ExternalIdentity.provider == "GOOGLE",
            ExternalIdentity.issuer == canonical_issuer,
            ExternalIdentity.provider_subject == canonical_subject,
        )
        .with_for_update()
    )
    if subject_owner is not None and subject_owner.user_account_id != locked.id:
        raise MembershipError("이 Google 계정은 다른 계정에 이미 연결되어 있습니다.")
    if current_identity is not None:
        if (
            current_identity.issuer == canonical_issuer
            and current_identity.provider_subject == canonical_subject
        ):
            return current_identity
        raise MembershipError("다른 Google 계정이 이미 연결되어 있습니다.")

    identity = ExternalIdentity(
        user_account_id=locked.id,
        provider="GOOGLE",
        issuer=CANONICAL_GOOGLE_ISSUER,
        provider_subject=canonical_subject,
    )
    session.add(identity)
    if locked.email_verified_at is None:
        locked.email_verified_at = occurred_at
        _audit(session, user=locked, event_type="EMAIL_VERIFIED", occurred_at=occurred_at)
    locked.auth_version += 1
    _audit(session, user=locked, event_type="GOOGLE_LINKED", occurred_at=occurred_at)
    return identity


def disconnect_google_identity(
    session: Session,
    *,
    user: UserAccount,
    current_password: str,
    occurred_at: datetime,
) -> None:
    _aware(occurred_at)
    locked = _locked_user(session, user.id)
    _require_mutable_user(locked, active=True)
    if locked.password_hash is None or (
        locked.login_name is None and locked.email_verified_at is None
    ):
        raise MembershipError("대체 로컬 로그인 수단이 있어야 Google 연결을 해제할 수 있습니다.")
    if not check_password_hash(locked.password_hash, current_password):
        raise MembershipError("현재 비밀번호를 확인하세요.")
    identity = session.scalar(
        select(ExternalIdentity)
        .where(
            ExternalIdentity.user_account_id == locked.id,
            ExternalIdentity.provider == "GOOGLE",
        )
        .with_for_update()
    )
    if identity is None:
        return
    session.delete(identity)
    locked.auth_version += 1
    _audit(session, user=locked, event_type="GOOGLE_UNLINKED", occurred_at=occurred_at)


__all__ = [
    "ACCOUNT_TOKEN_PURPOSES",
    "EMAIL_VERIFICATION",
    "EMAIL_VERIFICATION_TTL",
    "PASSWORD_RESET",
    "PASSWORD_RESET_TTL",
    "account_token_is_usable",
    "change_password",
    "connect_google_identity",
    "disconnect_google_identity",
    "google_identity_for_user",
    "issue_email_verification_token",
    "issue_password_reset_token",
    "reset_password_with_token",
    "verify_email_token",
]
