from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from flask import (
    Blueprint,
    Response,
    abort,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    admin_required,
    approval_required,
    csrf_token,
    is_demo_user,
    require_csrf,
    session_user,
)
from app.database import db
from app.models import UserAccount
from app.services.membership import (
    MembershipError,
    approve_pending_member,
    change_member_role,
    change_member_status,
)

bp = Blueprint("members", __name__, url_prefix="/admin/members")


def _private(content: str, status: int = 200) -> Response:
    response = make_response(content, status)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; img-src 'self' data:; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


def _render_members(*, error: str | None = None, status: int = 200) -> Response:
    current_user = session_user()
    assert current_user is not None
    demo_mode = is_demo_user(current_user)
    if demo_mode:
        rows: tuple[UserAccount, ...] = ()
    else:
        query = select(UserAccount)
        if current_user.role == "ASSISTANT_ADMIN":
            query = query.where(
                UserAccount.role.in_(("MEMBER", "STUDENT", "TEACHER")),
                UserAccount.status == "PENDING_APPROVAL",
            )
        rows = tuple(
            cast(Session, db.session).scalars(
                query.order_by(UserAccount.status, UserAccount.created_at, UserAccount.id)
            )
        )
    return _private(
        render_template(
            "admin_members.html",
            current_user=current_user,
            members=rows,
            csrf_token=csrf_token(),
            error=error,
            message=request.args.get("message"),
            demo_mode=demo_mode,
        ),
        status,
    )


@bp.get("")
@approval_required
def index() -> Response:
    return _render_members()


def _target(user_id: str) -> UserAccount:
    target = cast(Session, db.session).get(UserAccount, user_id)
    if target is None:
        abort(404)
    return target


@bp.post("/<user_id>/approve")
@approval_required
def approve(user_id: str) -> Any:
    require_csrf()
    actor = session_user()
    assert actor is not None
    try:
        approve_pending_member(
            cast(Session, db.session),
            actor=actor,
            target=_target(user_id),
            occurred_at=datetime.now(UTC),
        )
        db.session.commit()
    except MembershipError as error:
        db.session.rollback()
        return _render_members(error=str(error), status=409)
    return redirect(url_for("members.index", message="approved"))


@bp.post("/<user_id>/role")
@admin_required
def change_role(user_id: str) -> Any:
    require_csrf()
    actor = session_user()
    assert actor is not None
    try:
        change_member_role(
            cast(Session, db.session),
            actor=actor,
            target=_target(user_id),
            new_role=request.form.get("role", ""),
            occurred_at=datetime.now(UTC),
        )
        db.session.commit()
    except MembershipError as error:
        db.session.rollback()
        return _render_members(error=str(error), status=409)
    return redirect(url_for("members.index", message="role_changed"))


@bp.post("/<user_id>/status")
@admin_required
def change_status(user_id: str) -> Any:
    require_csrf()
    actor = session_user()
    assert actor is not None
    try:
        change_member_status(
            cast(Session, db.session),
            actor=actor,
            target=_target(user_id),
            new_status=request.form.get("status", ""),
            occurred_at=datetime.now(UTC),
        )
        db.session.commit()
    except MembershipError as error:
        db.session.rollback()
        return _render_members(error=str(error), status=409)
    return redirect(url_for("members.index", message="status_changed"))
