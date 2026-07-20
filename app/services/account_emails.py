from __future__ import annotations

import re
import smtplib
import ssl
from collections.abc import Callable, MutableSequence
from email.message import EmailMessage
from typing import cast
from urllib.parse import quote, urlparse

from flask import current_app


class AccountEmailError(RuntimeError):
    """계정 메일 전송 실패를 비밀값 없이 호출자에게 전달한다."""


AccountEmailTransport = Callable[[EmailMessage], None]
AccountEmailOutbox = MutableSequence[EmailMessage]

_GENERIC_DELIVERY_ERROR = "계정 이메일을 전송할 수 없습니다. 잠시 후 다시 시도하세요."
_BARE_EMAIL_ADDRESS = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+\Z")


def _nonempty_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or "\n" in normalized or "\r" in normalized:
        return None
    return normalized


def _credential_string(value: object) -> str | None:
    if not isinstance(value, str) or not value or "\n" in value or "\r" in value:
        return None
    return value


def _bare_email_address(value: object) -> str | None:
    normalized = _nonempty_string(value)
    if normalized is None or len(normalized) > 320:
        return None
    return normalized if _BARE_EMAIL_ADDRESS.fullmatch(normalized) else None


def _public_base_url(value: object) -> str | None:
    normalized = _nonempty_string(value)
    if normalized is None:
        return None
    parsed = urlparse(normalized)
    configured_root = current_app.config.get("APPLICATION_ROOT", "/")
    expected_path = ""
    if isinstance(configured_root, str) and configured_root.strip() not in {"", "/"}:
        expected_path = configured_root.strip().rstrip("/")
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.path.rstrip("/") != expected_path
        or parsed.params
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        return None
    return normalized.rstrip("/")


def _positive_int(value: object, *, maximum: int) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(cast(str | int, value))
    except (TypeError, ValueError):
        return None
    return parsed if 0 < parsed <= maximum else None


def _positive_float(value: object, *, maximum: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(cast(str | int | float, value))
    except (TypeError, ValueError):
        return None
    return parsed if 0 < parsed <= maximum else None


def _smtp_settings() -> tuple[str, int, str, str, bool, float] | None:
    host = _nonempty_string(current_app.config.get("SMTP_HOST"))
    port = _positive_int(current_app.config.get("SMTP_PORT"), maximum=65535)
    username = _credential_string(current_app.config.get("SMTP_USERNAME"))
    password = _credential_string(current_app.config.get("SMTP_PASSWORD"))
    timeout = _positive_float(current_app.config.get("SMTP_TIMEOUT_SECONDS"), maximum=30.0)
    use_starttls = current_app.config.get("SMTP_USE_STARTTLS") is True
    if None in {host, port, username, password, timeout}:
        return None
    assert host is not None
    assert port is not None
    assert username is not None
    assert password is not None
    assert timeout is not None
    return host, port, username, password, use_starttls, timeout


def account_email_available() -> bool:
    """현재 앱에서 계정 메일을 안전하게 전달할 수 있는지 반환한다."""

    if current_app.config.get("ACCOUNT_EMAIL_ENABLED") is not True:
        return False
    if _public_base_url(current_app.config.get("PUBLIC_BASE_URL")) is None:
        return False
    if _bare_email_address(current_app.config.get("EMAIL_FROM_ADDRESS")) is None:
        return False
    if callable(current_app.config.get("ACCOUNT_EMAIL_TRANSPORT")):
        return True
    outbox = current_app.config.get("ACCOUNT_EMAIL_OUTBOX")
    if outbox is not None and callable(getattr(outbox, "append", None)):
        return True
    return _smtp_settings() is not None


def _account_link(path: str, raw_token: str) -> str:
    base_url = _public_base_url(current_app.config.get("PUBLIC_BASE_URL"))
    if base_url is None or not isinstance(raw_token, str) or not raw_token or len(raw_token) > 2048:
        raise AccountEmailError(_GENERIC_DELIVERY_ERROR)
    encoded_token = quote(raw_token, safe="")
    return f"{base_url}{path}?token={encoded_token}"


def _message(*, to: str, subject: str, body: str) -> EmailMessage:
    recipient = _bare_email_address(to)
    sender = _bare_email_address(current_app.config.get("EMAIL_FROM_ADDRESS"))
    if recipient is None or sender is None:
        raise AccountEmailError(_GENERIC_DELIVERY_ERROR)
    try:
        message = EmailMessage()
        message["To"] = recipient
        message["From"] = sender
        message["Subject"] = subject
        message.set_content(body)
    except (TypeError, ValueError):
        raise AccountEmailError(_GENERIC_DELIVERY_ERROR) from None
    return message


def _deliver(message: EmailMessage) -> None:
    if current_app.config.get("ACCOUNT_EMAIL_ENABLED") is not True:
        raise AccountEmailError(_GENERIC_DELIVERY_ERROR)

    transport = current_app.config.get("ACCOUNT_EMAIL_TRANSPORT")
    outbox = current_app.config.get("ACCOUNT_EMAIL_OUTBOX")
    try:
        if callable(transport):
            cast(AccountEmailTransport, transport)(message)
            return
        if outbox is not None and callable(getattr(outbox, "append", None)):
            cast(AccountEmailOutbox, outbox).append(message)
            return

        settings = _smtp_settings()
        if settings is None:
            raise AccountEmailError(_GENERIC_DELIVERY_ERROR)
        host, port, username, password, use_starttls, timeout = settings
        with smtplib.SMTP(host=host, port=port, timeout=timeout) as smtp:
            smtp.ehlo()
            if use_starttls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            smtp.login(username, password)
            smtp.send_message(message)
    except AccountEmailError:
        raise
    except Exception:
        raise AccountEmailError(_GENERIC_DELIVERY_ERROR) from None


def send_email_verification(*, recipient: str, raw_token: str) -> None:
    link = _account_link("/auth/email/verify", raw_token)
    message = _message(
        to=recipient,
        subject="[전문대 입시상담] 이메일 주소를 인증해 주세요",
        body=(
            "전문대 입시상담 계정의 이메일 주소를 인증하려면 아래 링크를 여세요.\n\n"
            f"{link}\n\n"
            "이 요청을 하지 않았다면 이 메일을 무시하세요."
        ),
    )
    _deliver(message)


def send_password_reset(*, recipient: str, raw_token: str) -> None:
    link = _account_link("/auth/password/reset", raw_token)
    message = _message(
        to=recipient,
        subject="[전문대 입시상담] 비밀번호를 재설정해 주세요",
        body=(
            "전문대 입시상담 계정의 비밀번호를 재설정하려면 아래 링크를 여세요.\n\n"
            f"{link}\n\n"
            "이 요청을 하지 않았다면 이 메일을 무시하세요."
        ),
    )
    _deliver(message)


__all__ = [
    "AccountEmailError",
    "account_email_available",
    "send_email_verification",
    "send_password_reset",
]
