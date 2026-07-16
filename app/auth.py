from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any, cast
from urllib.parse import unquote, urlparse

import click
from flask import Flask, abort, current_app, g, redirect, request, session, url_for
from flask.cli import AppGroup
from sqlalchemy.orm import Session

from app.database import db
from app.models import UserAccount
from app.services.membership import MembershipError, bootstrap_admin


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    session["admin_csrf_token"] = token
    return token


def require_csrf() -> None:
    expected = session.get("csrf_token") or session.get("admin_csrf_token")
    supplied = request.form.get("csrf_token", "")
    if not isinstance(expected, str) or not hmac.compare_digest(expected, supplied):
        abort(400)


def safe_next(value: str | None) -> str | None:
    if not value or not value.startswith("/") or value.startswith("//"):
        return None
    decoded = unquote(value)
    if decoded.startswith("//") or "\\" in decoded or any(ord(char) < 32 for char in decoded):
        return None
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return None
    return value


def start_user_session(user: UserAccount) -> None:
    session.clear()
    token = secrets.token_urlsafe(32)
    session.update(
        user_id=user.id,
        auth_version=user.auth_version,
        authenticated_at=datetime.now(UTC).isoformat(),
        csrf_token=token,
        admin_csrf_token=token,
    )


def _legacy_admin_allowed() -> bool:
    return bool(current_app.config.get("ALLOW_LEGACY_ADMIN_LOGIN"))


def _legacy_admin_authenticated() -> bool:
    actor = session.get("admin_actor_ref")
    return _legacy_admin_allowed() and isinstance(actor, str) and bool(actor)


def session_user() -> UserAccount | None:
    cached = getattr(g, "authenticated_user", None)
    if isinstance(cached, UserAccount):
        return cached
    user_id = session.get("user_id")
    auth_version = session.get("auth_version")
    if not isinstance(user_id, str) or not isinstance(auth_version, int):
        return None
    if not current_app.config.get("DATABASE_URL"):
        session.clear()
        return None
    user = cast(Session, db.session).get(UserAccount, user_id)
    if user is None or user.auth_version != auth_version:
        session.clear()
        return None
    g.authenticated_user = user
    return user


def actor_ref() -> str:
    user = session_user()
    if user is not None:
        return user.actor_ref
    if _legacy_admin_authenticated():
        actor = session.get("admin_actor_ref")
        assert isinstance(actor, str)
        return actor
    abort(401)


def roles_required(
    *allowed_roles: str, allow_legacy: bool = True
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    roles = frozenset(allowed_roles)

    def decorate(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            user = session_user()
            if user is None:
                if allow_legacy and _legacy_admin_authenticated():
                    return view(*args, **kwargs)
                next_path = request.path if request.method == "GET" else None
                login_endpoint = "admin.login" if roles == {"ADMIN"} else "auth.login"
                return redirect(url_for(login_endpoint, next=next_path))
            if user.status != "ACTIVE":
                return redirect(url_for("auth.pending"))
            if roles and user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorate


member_required = roles_required("ADMIN", "ASSISTANT_ADMIN", "MEMBER")
admin_required = roles_required("ADMIN")
approval_required = roles_required("ADMIN", "ASSISTANT_ADMIN", allow_legacy=False)


def post_login_destination(user: UserAccount, requested_next: str | None = None) -> str:
    candidate = safe_next(requested_next)
    if candidate:
        return candidate
    if user.role == "ADMIN":
        return url_for("admin.rules")
    return url_for("admin.new_consultation")


def register_auth_cli(app: Flask) -> None:
    group = AppGroup("auth")

    @group.command("bootstrap-admin")
    def bootstrap_admin_command() -> None:
        """환경변수 관리자를 DB 활성 관리자 계정으로 멱등 생성한다."""
        login_name = current_app.config.get("ADMIN_USERNAME")
        password_hash = current_app.config.get("ADMIN_PASSWORD_HASH")
        if not isinstance(login_name, str) or not isinstance(password_hash, str):
            raise click.ClickException("관리자 부트스트랩 설정이 없습니다.")
        if not current_app.config.get("DATABASE_URL"):
            raise click.ClickException("관리자 부트스트랩용 데이터베이스 설정이 없습니다.")
        database_session = cast(Session, db.session)
        try:
            bootstrap_admin(
                database_session,
                login_name=login_name,
                password_hash=password_hash,
                occurred_at=datetime.now(UTC),
            )
            database_session.commit()
        except MembershipError as error:
            database_session.rollback()
            raise click.ClickException(str(error)) from error
        click.echo("관리자 계정 부트스트랩 확인 완료")

    app.cli.add_command(group)
