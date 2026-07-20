from __future__ import annotations

from email.message import EmailMessage

import pytest
from flask import Flask

from app.services import account_emails
from app.services.account_emails import (
    AccountEmailError,
    account_email_available,
    send_email_verification,
    send_password_reset,
)


def _email_app(**overrides: object) -> Flask:
    app = Flask(__name__)
    app.config.update(
        ACCOUNT_EMAIL_ENABLED=True,
        PUBLIC_BASE_URL="https://service.example.test",
        EMAIL_FROM_ADDRESS="accounts@service.example.test",
        SMTP_HOST="smtp.example.test",
        SMTP_PORT="587",
        SMTP_USERNAME="synthetic-user",
        SMTP_PASSWORD="synthetic-secret",
        SMTP_USE_STARTTLS=True,
        SMTP_TIMEOUT_SECONDS="5",
        ACCOUNT_EMAIL_OUTBOX=None,
        ACCOUNT_EMAIL_TRANSPORT=None,
    )
    app.config.update(overrides)
    return app


def test_outbox_uses_configured_base_url_and_query_token_not_request_host() -> None:
    outbox: list[EmailMessage] = []
    app = _email_app(
        ACCOUNT_EMAIL_OUTBOX=outbox,
        SMTP_HOST=None,
        SMTP_USERNAME=None,
        SMTP_PASSWORD=None,
    )

    with app.test_request_context("/", base_url="https://attacker.example.test"):
        assert account_email_available() is True
        send_email_verification(
            recipient="member@example.test",
            raw_token="synthetic/token with ?query",
        )
        send_password_reset(
            recipient="member@example.test",
            raw_token="synthetic-reset-token",
        )

    assert len(outbox) == 2
    verification_body = outbox[0].get_content()
    reset_body = outbox[1].get_content()
    assert outbox[0]["To"] == "member@example.test"
    assert outbox[0]["From"] == "accounts@service.example.test"
    assert (
        "https://service.example.test/auth/email/verify?token=synthetic%2Ftoken%20with%20%3Fquery"
    ) in verification_body
    assert (
        "https://service.example.test/auth/password/reset?token=synthetic-reset-token" in reset_body
    )
    assert "attacker.example.test" not in verification_body
    assert "attacker.example.test" not in reset_body


def test_disabled_or_incomplete_email_backend_is_unavailable_and_fails_generically() -> None:
    app = _email_app(ACCOUNT_EMAIL_ENABLED=False)
    with app.app_context():
        assert account_email_available() is False
        with pytest.raises(AccountEmailError) as caught:
            send_email_verification(
                recipient="member@example.test",
                raw_token="never-expose-this-token",
            )

    assert "never-expose-this-token" not in str(caught.value)

    app = _email_app(SMTP_PASSWORD=None)
    with app.app_context():
        assert account_email_available() is False


def test_injected_transport_failure_does_not_expose_original_exception() -> None:
    raw_token = "transport-secret-token"

    def failing_transport(_message: EmailMessage) -> None:
        raise LookupError(f"upstream leaked {raw_token}")

    app = _email_app(ACCOUNT_EMAIL_TRANSPORT=failing_transport)
    with app.app_context(), pytest.raises(AccountEmailError) as caught:
        send_password_reset(recipient="member@example.test", raw_token=raw_token)

    assert raw_token not in str(caught.value)
    assert "upstream" not in str(caught.value)
    assert caught.value.__cause__ is None


def test_smtp_transport_requires_starttls_before_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[object, ...]] = []
    tls_context = object()

    class SyntheticSmtp:
        def __init__(self, *, host: str, port: int, timeout: float) -> None:
            calls.append(("connect", host, port, timeout))

        def __enter__(self) -> SyntheticSmtp:
            return self

        def __exit__(self, *_args: object) -> None:
            calls.append(("close",))

        def ehlo(self) -> None:
            calls.append(("ehlo",))

        def starttls(self, *, context: object) -> None:
            calls.append(("starttls", context))

        def login(self, username: str, password: str) -> None:
            calls.append(("login", username, password))

        def send_message(self, message: EmailMessage) -> None:
            calls.append(("send", message["To"]))

    monkeypatch.setattr(account_emails.smtplib, "SMTP", SyntheticSmtp)
    monkeypatch.setattr(account_emails.ssl, "create_default_context", lambda: tls_context)
    app = _email_app()

    with app.app_context():
        assert account_email_available() is True
        send_email_verification(
            recipient="member@example.test",
            raw_token="synthetic-verification-token",
        )

    assert calls == [
        ("connect", "smtp.example.test", 587, 5.0),
        ("ehlo",),
        ("starttls", tls_context),
        ("ehlo",),
        ("login", "synthetic-user", "synthetic-secret"),
        ("send", "member@example.test"),
        ("close",),
    ]


@pytest.mark.parametrize(
    "recipient",
    ["missing-at-sign", "first@example.test,second@example.test", "a@example.test\nBcc:x@y.test"],
)
def test_recipient_must_be_one_bare_email_address(recipient: str) -> None:
    app = _email_app(ACCOUNT_EMAIL_OUTBOX=[])
    with app.app_context(), pytest.raises(AccountEmailError):
        send_email_verification(recipient=recipient, raw_token="synthetic-token")
