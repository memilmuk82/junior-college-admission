from __future__ import annotations

import hmac
from datetime import UTC, datetime
from typing import Any, cast

from authlib.integrations.base_client.errors import OAuthError
from flask import (
    Blueprint,
    Response,
    current_app,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from joserfc.errors import JoseError
from requests import RequestException
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash

from app.auth import (
    csrf_token,
    end_user_session,
    post_login_destination,
    require_csrf,
    safe_next,
    session_user,
    start_user_session,
)
from app.database import db
from app.services.google_oidc import google_oidc_client, verified_google_claims
from app.services.membership import (
    DemoRoleCredential,
    MembershipError,
    RegistrationConflict,
    active_demo_credentials,
    active_demo_role_credentials,
    authenticate_local_member,
    register_google_member,
    register_local_member,
)

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _account_type(value: str | None) -> str:
    return value if value in {"student", "teacher"} else "teacher"


def _registration_received_destination(
    *, requested_account_type: str | None, account_type: str, requested_next: str | None
) -> str:
    if requested_account_type in {"student", "teacher"}:
        if requested_next is not None:
            return url_for(
                "auth.registration_received",
                account_type=account_type,
                next=requested_next,
            )
        return url_for("auth.registration_received", account_type=account_type)
    if requested_next is not None:
        return url_for("auth.registration_received", next=requested_next)
    return url_for("auth.registration_received")


def _private(content: str, status: int = 200) -> Response:
    response = make_response(content, status)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self'; img-src 'self' data:; "
        "base-uri 'none'; form-action 'self' https://accounts.google.com; frame-ancestors 'none'"
    )
    return response


def login_view() -> Any:
    error: str | None = None
    requested_next = safe_next(request.values.get("next"))
    account_type = _account_type(request.values.get("account_type"))
    if request.method == "POST":
        require_csrf()
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        database_session = cast(Session, db.session)
        user = None
        if current_app.config.get("DATABASE_URL"):
            user = authenticate_local_member(
                database_session,
                login_name=username,
                password=password,
                occurred_at=datetime.now(UTC),
            )
        if user is not None:
            database_session.commit()
            start_user_session(user)
            if user.status != "ACTIVE":
                return redirect(url_for("auth.pending"))
            return redirect(post_login_destination(user, requested_next))

        configured_user = current_app.config.get("ADMIN_USERNAME")
        password_hash = current_app.config.get("ADMIN_PASSWORD_HASH")
        legacy_valid = (
            current_app.config.get("ALLOW_LEGACY_ADMIN_LOGIN")
            and isinstance(configured_user, str)
            and isinstance(password_hash, str)
            and hmac.compare_digest(username, configured_user)
            and check_password_hash(password_hash, password)
        )
        if legacy_valid:
            session.clear()
            token = csrf_token()
            session["admin_actor_ref"] = username
            session["admin_csrf_token"] = token
            return redirect(requested_next or url_for("admin.rules"))
        if current_app.config.get("DATABASE_URL"):
            database_session.rollback()
        error = "로그인 정보를 확인하세요."
    demo_credentials: tuple[DemoRoleCredential, ...] | None = None
    if current_app.config.get("DATABASE_URL"):
        database_session = cast(Session, db.session)
        try:
            demo_credentials = active_demo_role_credentials(
                database_session,
                public_password=current_app.config.get("DEMO_PUBLIC_PASSWORD"),
            )
            if demo_credentials is None:
                legacy = active_demo_credentials(
                    database_session,
                    login_name=current_app.config.get("DEMO_LOGIN_NAME"),
                    public_password=current_app.config.get("DEMO_PUBLIC_PASSWORD"),
                )
                if legacy is not None:
                    demo_credentials = (
                        DemoRoleCredential(
                            role="MEMBER",
                            label="기존 공개 체험",
                            login_name=legacy[0],
                            public_password=legacy[1],
                        ),
                    )
        except SQLAlchemyError:
            database_session.rollback()
    return _private(
        render_template(
            "auth_login.html",
            csrf_token=csrf_token(),
            error=error,
            google_enabled=bool(current_app.config.get("GOOGLE_OIDC_ENABLED")),
            demo_credentials=demo_credentials or (),
            demo_public_password=(
                None if demo_credentials is None else demo_credentials[0].public_password
            ),
            next=requested_next or "",
            account_type=account_type,
        ),
        401 if error else 200,
    )


@bp.route("/login", methods=["GET", "POST"])
def login() -> Any:
    return login_view()


@bp.route("/register", methods=["GET", "POST"])
def register() -> Any:
    errors: tuple[str, ...] = ()
    requested_next = safe_next(request.values.get("next"))
    requested_account_type = request.values.get("account_type")
    account_type = _account_type(requested_account_type)
    received_destination = _registration_received_destination(
        requested_account_type=requested_account_type,
        account_type=account_type,
        requested_next=requested_next,
    )
    if request.method == "POST":
        require_csrf()
        database_session = cast(Session, db.session)
        try:
            password = request.form.get("password", "")
            if not hmac.compare_digest(password, request.form.get("password_confirmation", "")):
                raise MembershipError("비밀번호 확인이 일치하지 않습니다.")
            register_local_member(
                database_session,
                login_name=request.form.get("login_name", ""),
                email=request.form.get("email", ""),
                display_name=request.form.get("display_name", ""),
                password=password,
                requested_role={"student": "STUDENT", "teacher": "TEACHER"}.get(
                    requested_account_type or ""
                ),
                requested_status=request.form.get("status"),
                occurred_at=datetime.now(UTC),
                reserved_login_name=current_app.config.get("DEMO_LOGIN_NAME"),
            )
            database_session.commit()
            return redirect(received_destination)
        except RegistrationConflict:
            database_session.rollback()
            return redirect(received_destination)
        except MembershipError as error:
            database_session.rollback()
            errors = (str(error),)
        except IntegrityError:
            database_session.rollback()
            return redirect(received_destination)
    return _private(
        render_template(
            "auth_register.html",
            csrf_token=csrf_token(),
            errors=errors,
            google_enabled=bool(current_app.config.get("GOOGLE_OIDC_ENABLED")),
            account_type=account_type,
            next=requested_next or "",
        ),
        400 if errors else 200,
    )


@bp.get("/registration-received")
def registration_received() -> Any:
    return _private(
        render_template(
            "auth_registration_received.html",
            account_type=_account_type(request.args.get("account_type")),
            next=safe_next(request.args.get("next")) or "",
        )
    )


@bp.get("/pending")
def pending() -> Any:
    user = session_user()
    if user is None:
        return redirect(url_for("auth.login"))
    if user.status == "ACTIVE":
        return redirect(post_login_destination(user))
    return _private(render_template("auth_pending.html", user=user, csrf_token=csrf_token()))


@bp.post("/logout")
def logout() -> Any:
    require_csrf()
    end_user_session()
    return redirect(url_for("auth.login"))


def _google_redirect_uri() -> str:
    configured = current_app.config.get("GOOGLE_REDIRECT_URI")
    if isinstance(configured, str) and configured:
        return configured
    return url_for("auth.google_callback", _external=True)


@bp.get("/google/start")
def google_start() -> Any:
    try:
        return google_oidc_client().authorize_redirect(_google_redirect_uri())
    except MembershipError as error:
        return _private(str(error), 503)
    except (OAuthError, JoseError, RequestException, RuntimeError):
        current_app.logger.warning("Google OIDC 시작에 실패했습니다.")
        return _private("Google 로그인을 시작할 수 없습니다.", 503)


@bp.get("/google/callback")
def google_callback() -> Any:
    database_session = cast(Session, db.session)
    try:
        token = google_oidc_client().authorize_access_token()
        claims = verified_google_claims(token)
        user = register_google_member(
            database_session,
            issuer=cast(str, claims["issuer"]),
            subject=cast(str, claims["subject"]),
            email=cast(str, claims["email"]),
            email_verified=claims["email_verified"] is True,
            display_name=cast(str, claims["display_name"]),
            occurred_at=datetime.now(UTC),
        )
        database_session.commit()
    except (
        MembershipError,
        OAuthError,
        JoseError,
        RequestException,
        RuntimeError,
        IntegrityError,
    ):
        database_session.rollback()
        current_app.logger.warning("Google OIDC 로그인 검증에 실패했습니다.")
        return _private("Google 로그인을 완료할 수 없습니다.", 401)
    start_user_session(user)
    if user.status != "ACTIVE":
        return redirect(url_for("auth.pending"))
    return redirect(post_login_destination(user))
