from __future__ import annotations

import hmac
import secrets
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from typing import Any, cast

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash

from app.database import db
from app.models import RuleVersionLineage
from app.services.rule_admin import (
    HumanApproval,
    RuleAdministrationError,
    clone_published_rule_as_draft,
    compare_rule_payloads,
    human_approve_tested_rule,
    publish_human_approved_rule,
    rule_model_for_type,
)

bp = Blueprint("admin", __name__, url_prefix="/admin")

RULE_TYPE_LABELS = {
    "ADMISSION_ELIGIBILITY_RULE": "지원자격",
    "GRADE_SOURCE_SCOPE_RULE": "성적 범위",
    "SCORE_RULE": "성적 계산",
    "MULTIPLE_APPLICATION_RULE": "복수지원",
    "DISQUALIFICATION_RULE": "결격",
}


def _csrf_token() -> str:
    token = session.get("admin_csrf_token")
    if not isinstance(token, str):
        token = secrets.token_urlsafe(32)
        session["admin_csrf_token"] = token
    return token


def _require_csrf() -> None:
    expected = session.get("admin_csrf_token")
    supplied = request.form.get("csrf_token", "")
    if not isinstance(expected, str) or not hmac.compare_digest(expected, supplied):
        abort(400)


def _private(content: str, status: int = 200) -> Response:
    response = make_response(content, status)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


def _actor_ref() -> str:
    actor = session.get("admin_actor_ref")
    if not isinstance(actor, str) or not actor:
        abort(401)
    return actor


def admin_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        actor = session.get("admin_actor_ref")
        if not isinstance(actor, str) or not actor:
            return redirect(url_for("admin.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login() -> Any:
    error: str | None = None
    if request.method == "POST":
        _require_csrf()
        configured_user = current_app.config.get("ADMIN_USERNAME")
        password_hash = current_app.config.get("ADMIN_PASSWORD_HASH")
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        valid = (
            isinstance(configured_user, str)
            and isinstance(password_hash, str)
            and hmac.compare_digest(username, configured_user)
            and check_password_hash(password_hash, password)
        )
        if valid:
            session.clear()
            session["admin_actor_ref"] = username
            session["admin_csrf_token"] = secrets.token_urlsafe(32)
            return redirect(url_for("admin.rules"))
        error = "관리자 인증 정보를 확인하세요."
    return _private(
        render_template("admin_login.html", csrf_token=_csrf_token(), error=error),
        401 if error else 200,
    )


@bp.post("/logout")
@admin_required
def logout() -> Any:
    _require_csrf()
    session.clear()
    return redirect(url_for("admin.login"))


@bp.get("/rules")
@admin_required
def rules() -> Response:
    database_session = cast(Session, db.session)
    grouped: list[tuple[str, str, tuple[Any, ...]]] = []
    for rule_type, label in RULE_TYPE_LABELS.items():
        model = rule_model_for_type(rule_type)
        rows = tuple(database_session.scalars(select(model).order_by(model.created_at.desc())))
        grouped.append((rule_type, label, rows))
    return _private(
        render_template(
            "admin_rules.html",
            grouped=tuple(grouped),
            csrf_token=_csrf_token(),
            actor_ref=_actor_ref(),
        )
    )


def _rule_detail(rule_type: str, rule_id: str) -> tuple[Any, Any | None, tuple[Any, ...]]:
    if rule_type not in RULE_TYPE_LABELS:
        abort(404)
    database_session = cast(Session, db.session)
    model = rule_model_for_type(rule_type)
    rule = database_session.get(model, rule_id)
    if rule is None:
        abort(404)
    lineage = database_session.scalar(
        select(RuleVersionLineage).where(
            RuleVersionLineage.rule_type == rule_type,
            RuleVersionLineage.rule_id == rule.id,
        )
    )
    previous = None if lineage is None else database_session.get(model, lineage.supersedes_rule_id)
    changes = (
        () if previous is None else compare_rule_payloads(previous.rule_payload, rule.rule_payload)
    )
    return rule, previous, changes


@bp.get("/rules/<rule_type>/<rule_id>")
@admin_required
def rule_detail(rule_type: str, rule_id: str) -> Response:
    rule, previous, changes = _rule_detail(rule_type, rule_id)
    return _render_rule_detail(rule_type, rule, previous, changes)


def _render_rule_detail(
    rule_type: str,
    rule: Any,
    previous: Any | None,
    changes: tuple[Any, ...],
    *,
    error: str | None = None,
    status: int = 200,
) -> Response:
    return _private(
        render_template(
            "admin_rule_detail.html",
            rule_type=rule_type,
            rule_type_label=RULE_TYPE_LABELS[rule_type],
            rule=rule,
            previous=previous,
            changes=changes,
            error=error,
            csrf_token=_csrf_token(),
            actor_ref=_actor_ref(),
        ),
        status,
    )


@bp.post("/rules/<rule_type>/<rule_id>/clone")
@admin_required
def clone_rule(rule_type: str, rule_id: str) -> Any:
    _require_csrf()
    try:
        draft = clone_published_rule_as_draft(
            cast(Session, db.session),
            rule_type=rule_type,
            source_rule_id=rule_id,
            new_version=request.form.get("new_version", ""),
            actor_ref=_actor_ref(),
            change_reason=request.form.get("change_reason", ""),
            occurred_at=datetime.now(UTC),
        )
        db.session.commit()
    except RuleAdministrationError as error:
        db.session.rollback()
        rule, previous, changes = _rule_detail(rule_type, rule_id)
        return _render_rule_detail(rule_type, rule, previous, changes, error=str(error), status=400)
    return redirect(url_for("admin.rule_detail", rule_type=rule_type, rule_id=draft.id))


@bp.post("/rules/<rule_type>/<rule_id>/approve")
@admin_required
def approve_rule(rule_type: str, rule_id: str) -> Any:
    _require_csrf()
    try:
        human_approve_tested_rule(
            cast(Session, db.session),
            rule_type=rule_type,
            rule_id=rule_id,
            approval=HumanApproval(
                actor_ref=_actor_ref(),
                approved_at=datetime.now(UTC),
                confirmation=request.form.get("confirmation", ""),
            ),
        )
        db.session.commit()
    except RuleAdministrationError as error:
        db.session.rollback()
        rule, previous, changes = _rule_detail(rule_type, rule_id)
        return _render_rule_detail(rule_type, rule, previous, changes, error=str(error), status=400)
    return redirect(url_for("admin.rule_detail", rule_type=rule_type, rule_id=rule_id))


@bp.post("/rules/<rule_type>/<rule_id>/publish")
@admin_required
def publish_rule(rule_type: str, rule_id: str) -> Any:
    _require_csrf()
    try:
        publish_human_approved_rule(
            cast(Session, db.session),
            rule_type=rule_type,
            rule_id=rule_id,
            actor_ref=_actor_ref(),
            occurred_at=datetime.now(UTC),
        )
        db.session.commit()
    except RuleAdministrationError as error:
        db.session.rollback()
        rule, previous, changes = _rule_detail(rule_type, rule_id)
        return _render_rule_detail(rule_type, rule, previous, changes, error=str(error), status=400)
    return redirect(url_for("admin.rule_detail", rule_type=rule_type, rule_id=rule_id))
