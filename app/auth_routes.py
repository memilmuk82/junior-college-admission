from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from email.message import EmailMessage
from typing import Any, cast
from urllib.parse import urlparse

from authlib.integrations.base_client.errors import OAuthError
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
from joserfc.errors import JoseError
from requests import RequestException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash

from app.auth import (
    begin_google_oidc_intent,
    consume_google_oidc_intent,
    csrf_token,
    email_verification_pending,
    end_user_session,
    post_login_destination,
    require_csrf,
    safe_next,
    session_user,
    start_user_session,
)
from app.database import db
from app.models import UserAccount
from app.services.account_emails import (
    AccountEmailError,
    account_email_available,
    send_email_verification,
    send_password_reset,
)
from app.services.account_security import (
    account_token_is_usable,
    connect_google_identity,
    issue_email_verification_token,
    issue_password_reset_token,
    reset_password_with_token,
    verify_email_token,
)
from app.services.demo_sandbox import (
    DemoSandboxError,
    active_demo_sandbox_credentials,
    authenticate_demo_sandbox_gateway,
)
from app.services.google_oidc import (
    DEMO_GOOGLE_CLAIMS_SESSION_KEY,
    google_oidc_client,
    verified_google_claims,
)
from app.services.membership import (
    DEMO_ROLE_LOGIN_NAMES,
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
_OUTBOX_LINK = re.compile(r"https://[^\s<>]+")


def _google_enabled() -> bool:
    return bool(
        current_app.config.get("GOOGLE_OIDC_ENABLED")
        or current_app.config.get("DEMO_GOOGLE_STUB_ENABLED")
    )


def _demo_outbox_enabled() -> bool:
    return bool(
        current_app.config.get("DEMO_SANDBOX_ENABLED")
        and current_app.config.get("DEMO_EMAIL_OUTBOX_ENABLED")
    )


def _require_sandbox_example_email(value: str) -> None:
    if current_app.config.get("DEMO_SANDBOX_ENABLED") and not value.strip().lower().endswith(
        ".invalid"
    ):
        raise MembershipError("체험 환경에는 개인정보가 아닌 .invalid 예시 이메일을 입력하세요.")


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
    configured_demo_entry = current_app.config.get("DEMO_SANDBOX_ENTRY_URL")
    demo_sandbox_entry_url = (
        configured_demo_entry
        if isinstance(configured_demo_entry, str)
        and configured_demo_entry.startswith("/demo/")
        and safe_next(configured_demo_entry) == configured_demo_entry
        else None
    )
    if request.method == "POST":
        require_csrf()
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        database_session = cast(Session, db.session)
        user = None
        if current_app.config.get("DATABASE_URL"):
            try:
                if current_app.config.get("DEMO_SANDBOX_ENABLED"):
                    user = authenticate_demo_sandbox_gateway(
                        database_session,
                        config=current_app.config,
                        login_name=username,
                        password=password,
                        occurred_at=datetime.now(UTC),
                    )
                if user is None:
                    user = authenticate_local_member(
                        database_session,
                        login_name=username,
                        password=password,
                        occurred_at=datetime.now(UTC),
                    )
            except DemoSandboxError:
                database_session.rollback()
                current_app.logger.warning("체험 역할 계정 로그인을 복구할 수 없습니다.")
                user = None
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
            and username == configured_user
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
            if current_app.config.get("DEMO_SANDBOX_ENABLED"):
                sandbox_credentials = active_demo_sandbox_credentials(
                    database_session,
                    config=current_app.config,
                )
                demo_credentials = (
                    None
                    if sandbox_credentials is None
                    else tuple(
                        DemoRoleCredential(
                            role=item.role,
                            label=item.label,
                            login_name=item.login_name,
                            public_password=item.public_password,
                        )
                        for item in sandbox_credentials
                    )
                )
            else:
                demo_credentials = active_demo_role_credentials(
                    database_session,
                    public_password=current_app.config.get("DEMO_PUBLIC_PASSWORD"),
                )
            if demo_credentials is None and not current_app.config.get("DEMO_SANDBOX_ENABLED"):
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
            google_enabled=_google_enabled(),
            demo_credentials=demo_credentials or (),
            demo_public_password=(
                None if demo_credentials is None else demo_credentials[0].public_password
            ),
            next=requested_next or "",
            account_type=account_type,
            message=request.args.get("message"),
            demo_sandbox_entry_url=demo_sandbox_entry_url,
        ),
        401 if error else 200,
    )


@bp.route("/login", methods=["GET", "POST"])
def login() -> Any:
    return login_view()


@bp.post("/demo-start/<role>")
def demo_start(role: str) -> Any:
    if current_app.config.get("DEMO_SANDBOX_ENABLED") is not True:
        abort(404)
    require_csrf()
    normalized_role = role.strip().upper()
    login_name = DEMO_ROLE_LOGIN_NAMES.get(normalized_role)
    public_password = current_app.config.get("DEMO_SANDBOX_PUBLIC_PASSWORD")
    if login_name is None or not isinstance(public_password, str):
        abort(404)
    database_session = cast(Session, db.session)
    try:
        user = authenticate_demo_sandbox_gateway(
            database_session,
            config=current_app.config,
            login_name=login_name,
            password=public_password,
            occurred_at=datetime.now(UTC),
        )
        if user is None:
            raise DemoSandboxError("체험 역할 계정을 시작할 수 없습니다.")
        database_session.commit()
    except DemoSandboxError:
        database_session.rollback()
        return _private("체험 역할 계정을 시작할 수 없습니다.", 503)
    start_user_session(user)
    return redirect(post_login_destination(user), code=303)


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
        if not account_email_available():
            return _private(
                render_template(
                    "auth_register.html",
                    csrf_token=csrf_token(),
                    errors=(
                        "인증 메일 발송 설정이 필요합니다. "
                        "기존 계정 로그인은 계속 사용할 수 있습니다.",
                    ),
                    google_enabled=_google_enabled(),
                    email_available=False,
                    account_type=account_type,
                    next=requested_next or "",
                    values={
                        "display_name": request.form.get("display_name", ""),
                        "email": request.form.get("email", ""),
                    },
                ),
                503,
            )
        try:
            password = request.form.get("password", "")
            if password != request.form.get("password_confirmation", ""):
                raise MembershipError("비밀번호 확인이 일치하지 않습니다.")
            _require_sandbox_example_email(request.form.get("email", ""))
            member = register_local_member(
                database_session,
                login_name=None,
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
            raw_token = issue_email_verification_token(
                database_session,
                user=member,
                target_email=member.email,
                occurred_at=datetime.now(UTC),
            )
            recipient = member.email
            database_session.commit()
        except RegistrationConflict:
            database_session.rollback()
            return redirect(received_destination)
        except MembershipError as error:
            database_session.rollback()
            errors = (str(error),)
        except IntegrityError:
            database_session.rollback()
            return redirect(received_destination)
        else:
            try:
                send_email_verification(recipient=recipient, raw_token=raw_token)
            except AccountEmailError:
                current_app.logger.warning("가입 인증 메일 발송을 완료할 수 없습니다.")
            return redirect(received_destination)
    return _private(
        render_template(
            "auth_register.html",
            csrf_token=csrf_token(),
            errors=errors,
            google_enabled=_google_enabled(),
            email_available=account_email_available(),
            account_type=account_type,
            next=requested_next or "",
            values={
                "display_name": request.form.get("display_name", ""),
                "email": request.form.get("email", ""),
            },
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


@bp.get("/demo-outbox")
def demo_outbox() -> Response:
    """Expose sandbox-only verification links without contacting a real mailbox."""

    if not _demo_outbox_enabled():
        abort(404)
    configured_outbox = current_app.config.get("ACCOUNT_EMAIL_OUTBOX")
    if not isinstance(configured_outbox, list):
        abort(503)
    public_base = current_app.config.get("PUBLIC_BASE_URL")
    if not isinstance(public_base, str):
        abort(503)
    expected = urlparse(public_base.rstrip("/"))
    messages: list[dict[str, str]] = []
    for raw_message in reversed(configured_outbox[-50:]):
        if not isinstance(raw_message, EmailMessage):
            continue
        body = raw_message.get_content()
        link = next(iter(_OUTBOX_LINK.findall(body)), "")
        parsed = urlparse(link)
        if (
            parsed.scheme != expected.scheme
            or parsed.netloc != expected.netloc
            or not parsed.path.startswith(f"{expected.path.rstrip('/')}/auth/")
        ):
            link = ""
        messages.append(
            {
                "recipient": str(raw_message.get("To", "")),
                "subject": str(raw_message.get("Subject", "")),
                "link": link,
            }
        )
    return _private(
        render_template(
            "auth_demo_outbox.html",
            messages=tuple(messages),
        )
    )


@bp.route("/email/resend", methods=["GET", "POST"])
def resend_email_verification() -> Any:
    if request.method == "GET":
        return _private(
            render_template(
                "auth_email_resend.html",
                csrf_token=csrf_token(),
                error=None,
                email_available=account_email_available(),
            )
        )
    require_csrf()
    if not account_email_available():
        return _private(
            render_template(
                "auth_email_resend.html",
                csrf_token=csrf_token(),
                error="인증 메일 발송 설정이 필요합니다.",
                email_available=False,
            ),
            503,
        )

    database_session = cast(Session, db.session)
    recipient: str | None = None
    raw_token: str | None = None
    try:
        email = request.form.get("email", "").strip().lower()
        user = database_session.scalar(select(UserAccount).where(UserAccount.email == email))
        if user is not None and user.email_verified_at is None:
            raw_token = issue_email_verification_token(
                database_session,
                user=user,
                target_email=user.email,
                occurred_at=datetime.now(UTC),
            )
            recipient = user.email
            database_session.commit()
        else:
            database_session.rollback()
    except (MembershipError, IntegrityError):
        database_session.rollback()
        current_app.logger.warning("인증 메일 재발송 요청을 완료할 수 없습니다.")
    if recipient is not None and raw_token is not None:
        try:
            send_email_verification(recipient=recipient, raw_token=raw_token)
        except AccountEmailError:
            current_app.logger.warning("인증 메일 재발송을 완료할 수 없습니다.")
    return redirect(url_for("auth.registration_received"), code=303)


@bp.route("/email/verify", methods=["GET", "POST"])
def verify_email() -> Any:
    raw_token = (
        request.form.get("token", "") if request.method == "POST" else request.args.get("token", "")
    )
    database_session = cast(Session, db.session)
    now = datetime.now(UTC)
    if request.method == "GET":
        usable = account_token_is_usable(
            database_session,
            raw_token=raw_token,
            purpose="EMAIL_VERIFICATION",
            occurred_at=now,
        )
        return _private(
            render_template(
                "auth_email_verify.html",
                csrf_token=csrf_token(),
                token=raw_token if usable else "",
                error=None if usable else "인증 링크가 유효하지 않거나 만료되었습니다.",
            ),
            200 if usable else 400,
        )

    require_csrf()
    authenticated_user_id = session.get("user_id")
    try:
        verified_user = verify_email_token(
            database_session,
            raw_token=raw_token,
            occurred_at=now,
        )
        database_session.commit()
    except MembershipError as error:
        database_session.rollback()
        return _private(
            render_template(
                "auth_email_verify.html",
                csrf_token=csrf_token(),
                token="",
                error=str(error),
            ),
            400,
        )
    if authenticated_user_id == verified_user.id:
        start_user_session(verified_user)
        return redirect(url_for("auth.pending", message="email_verified"), code=303)
    return redirect(url_for("auth.login", message="email_verified"), code=303)


@bp.route("/password/forgot", methods=["GET", "POST"])
def forgot_password() -> Any:
    if request.method == "GET":
        return _private(
            render_template(
                "auth_password_forgot.html",
                csrf_token=csrf_token(),
                error=None,
                email_available=account_email_available(),
            )
        )
    require_csrf()
    if not account_email_available():
        return _private(
            render_template(
                "auth_password_forgot.html",
                csrf_token=csrf_token(),
                error="비밀번호 재설정 메일 발송 설정이 필요합니다.",
                email_available=False,
            ),
            503,
        )

    database_session = cast(Session, db.session)
    recipient: str | None = None
    raw_token: str | None = None
    try:
        issued = issue_password_reset_token(
            database_session,
            email=request.form.get("email", ""),
            occurred_at=datetime.now(UTC),
        )
        if issued is not None:
            user, raw_token = issued
            recipient = user.email
            database_session.commit()
        else:
            database_session.rollback()
    except (MembershipError, IntegrityError):
        database_session.rollback()
        current_app.logger.warning("비밀번호 재설정 메일 요청을 완료할 수 없습니다.")
    if recipient is not None and raw_token is not None:
        try:
            send_password_reset(recipient=recipient, raw_token=raw_token)
        except AccountEmailError:
            current_app.logger.warning("비밀번호 재설정 메일 발송을 완료할 수 없습니다.")
    return redirect(url_for("auth.password_requested"), code=303)


@bp.get("/password/requested")
def password_requested() -> Response:
    return _private(render_template("auth_password_requested.html"))


@bp.route("/password/reset", methods=["GET", "POST"])
def reset_password() -> Any:
    raw_token = (
        request.form.get("token", "") if request.method == "POST" else request.args.get("token", "")
    )
    database_session = cast(Session, db.session)
    now = datetime.now(UTC)
    if request.method == "GET":
        usable = account_token_is_usable(
            database_session,
            raw_token=raw_token,
            purpose="PASSWORD_RESET",
            occurred_at=now,
        )
        return _private(
            render_template(
                "auth_password_reset.html",
                csrf_token=csrf_token(),
                token=raw_token if usable else "",
                error=None if usable else "재설정 링크가 유효하지 않거나 만료되었습니다.",
                show_form=usable,
            ),
            200 if usable else 400,
        )

    require_csrf()
    new_password = request.form.get("new_password", "")
    if new_password != request.form.get("new_password_confirmation", ""):
        return _private(
            render_template(
                "auth_password_reset.html",
                csrf_token=csrf_token(),
                token=raw_token,
                error="비밀번호 확인이 일치하지 않습니다.",
                show_form=True,
            ),
            400,
        )
    if len(new_password) < 12 or len(new_password) > 256:
        return _private(
            render_template(
                "auth_password_reset.html",
                csrf_token=csrf_token(),
                token=raw_token,
                error="비밀번호는 12~256자로 입력하세요.",
                show_form=True,
            ),
            400,
        )
    try:
        reset_password_with_token(
            database_session,
            raw_token=raw_token,
            new_password=new_password,
            occurred_at=now,
        )
        database_session.commit()
    except MembershipError as error:
        database_session.rollback()
        return _private(
            render_template(
                "auth_password_reset.html",
                csrf_token=csrf_token(),
                token="",
                error=str(error),
                show_form=False,
            ),
            400,
        )
    end_user_session()
    return redirect(url_for("auth.login", message="password_reset"), code=303)


@bp.get("/pending")
def pending() -> Any:
    user = session_user()
    if user is None:
        return redirect(url_for("auth.login"))
    if user.status == "ACTIVE" and not email_verification_pending(user):
        return redirect(post_login_destination(user))
    return _private(
        render_template(
            "auth_pending.html",
            user=user,
            csrf_token=csrf_token(),
            email_pending=email_verification_pending(user),
            message=request.args.get("message"),
        )
    )


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
    user = session_user()
    link_intent = request.args.get("intent") == "link"
    if link_intent:
        stored_intent = session.get("google_oidc_intent")
        if (
            user is None
            or not isinstance(stored_intent, dict)
            or stored_intent.get("kind") != "link"
            or stored_intent.get("user_id") != user.id
            or stored_intent.get("auth_version") != user.auth_version
        ):
            return _private("Google 계정 연결 요청을 확인할 수 없습니다.", 401)
    else:
        if user is not None:
            return redirect(url_for("account.security"))
        begin_google_oidc_intent(
            kind="login",
            requested_next=safe_next(request.args.get("next")),
        )
    try:
        return google_oidc_client().authorize_redirect(_google_redirect_uri())
    except MembershipError as error:
        return _private(str(error), 503)
    except (OAuthError, JoseError, RequestException, RuntimeError):
        current_app.logger.warning("Google OIDC 시작에 실패했습니다.")
        return _private("Google 로그인을 시작할 수 없습니다.", 503)


@bp.route("/google/demo-consent", methods=["GET", "POST"])
def google_demo_consent() -> Any:
    if not (
        current_app.config.get("DEMO_SANDBOX_ENABLED")
        and current_app.config.get("DEMO_GOOGLE_STUB_ENABLED")
    ):
        abort(404)
    intent = session.get("google_oidc_intent")
    if not isinstance(intent, dict) or intent.get("kind") not in {"login", "link"}:
        return _private("Google 체험 요청이 만료되었습니다.", 401)
    user = session_user()
    if intent["kind"] == "link" and (
        user is None
        or intent.get("user_id") != user.id
        or intent.get("auth_version") != user.auth_version
    ):
        return _private("Google 계정 연결 요청을 확인할 수 없습니다.", 401)

    default_email = user.email if user is not None else "google-student@example.invalid"
    error: str | None = None
    if request.method == "POST":
        require_csrf()
        email = request.form.get("email", "").strip().lower()
        display_name = request.form.get("display_name", "").strip()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.invalid", email) or len(email) > 320:
            error = "체험 Google 주소는 개인정보가 아닌 .invalid 예시 이메일을 사용하세요."
        elif user is not None and intent["kind"] == "link" and email != user.email:
            error = "현재 계정의 인증 이메일과 같은 체험 Google 주소를 사용하세요."
        elif not display_name or len(display_name) > 120:
            error = "체험 Google 표시 이름은 1~120자로 입력하세요."
        else:
            instance_id = str(current_app.config.get("DEMO_SANDBOX_INSTANCE_ID", "demo"))
            subject = hashlib.sha256(f"{instance_id}:{email}".encode()).hexdigest()
            session[DEMO_GOOGLE_CLAIMS_SESSION_KEY] = {
                "userinfo": {
                    "iss": "https://accounts.google.com",
                    "sub": f"demo-{subject}",
                    "email": email,
                    "email_verified": True,
                    "name": display_name,
                }
            }
            return redirect(url_for("auth.google_callback"), code=303)
    return _private(
        render_template(
            "auth_google_demo_consent.html",
            csrf_token=csrf_token(),
            intent_kind=intent["kind"],
            email=(
                request.form.get("email", default_email)
                if request.method == "POST"
                else default_email
            ),
            display_name=(
                request.form.get(
                    "display_name", user.display_name if user is not None else "체험 Google 사용자"
                )
                if request.method == "POST"
                else (user.display_name if user is not None else "체험 Google 사용자")
            ),
            error=error,
        ),
        400 if error else 200,
    )


@bp.get("/google/callback")
def google_callback() -> Any:
    database_session = cast(Session, db.session)
    try:
        token = google_oidc_client().authorize_access_token()
        intent = consume_google_oidc_intent()
        if intent is None:
            raise MembershipError("Google 로그인 요청이 만료되었습니다.")
        claims = verified_google_claims(token)
        if intent["kind"] == "link":
            user = session_user()
            if (
                user is None
                or intent.get("user_id") != user.id
                or intent.get("auth_version") != user.auth_version
            ):
                raise MembershipError("Google 계정 연결 요청을 확인할 수 없습니다.")
            connect_google_identity(
                database_session,
                user=user,
                issuer=cast(str, claims["issuer"]),
                subject=cast(str, claims["subject"]),
                email=cast(str, claims["email"]),
                email_verified=claims["email_verified"] is True,
                occurred_at=datetime.now(UTC),
            )
        else:
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
    except MembershipError as error:
        database_session.rollback()
        current_app.logger.warning("Google OIDC 계정 인증을 완료할 수 없습니다.")
        if str(error) == "동일 이메일 계정은 관리자 확인 없이 자동 연결하지 않습니다.":
            return redirect(url_for("auth.login", message="google_link_required"), code=303)
        return _private("Google 로그인을 완료할 수 없습니다.", 401)
    except (
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
    if intent["kind"] == "link":
        return redirect(url_for("account.security", message="google_connected"), code=303)
    if user.status != "ACTIVE":
        return redirect(url_for("auth.pending"))
    return redirect(post_login_destination(user, cast(str | None, intent.get("requested_next"))))
