from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.auth import safe_next
from app.services.google_oidc import verified_google_claims
from app.services.membership import MembershipError


@pytest.mark.parametrize(
    "value",
    [
        "https://evil.example/",
        "//evil.example/",
        "/\\evil.example/",
        "/%5cevil.example/",
        "/%2f%2fevil.example/",
        "",
        None,
    ],
)
def test_safe_next_rejects_external_or_empty_targets(value: str | None) -> None:
    assert safe_next(value) is None


def test_safe_next_accepts_only_local_absolute_path() -> None:
    assert safe_next("/admin/consultations/new?step=1") == "/admin/consultations/new?step=1"


def test_verified_google_claims_require_verified_email_and_google_issuer() -> None:
    claims = verified_google_claims(
        {
            "userinfo": {
                "iss": "accounts.google.com",
                "sub": "synthetic-subject",
                "email": "oidc-user@example.invalid",
                "email_verified": True,
                "name": "합성 OIDC 사용자",
            }
        }
    )
    assert claims["issuer"] == "https://accounts.google.com"
    assert claims["subject"] == "synthetic-subject"
    assert claims["email_verified"] is True

    with pytest.raises(MembershipError):
        verified_google_claims(
            {
                "userinfo": {
                    "iss": "https://untrusted.example.invalid",
                    "sub": "synthetic-subject",
                    "email": "oidc-user@example.invalid",
                    "email_verified": True,
                }
            }
        )


def test_verified_google_claims_does_not_accept_string_true() -> None:
    with pytest.raises(MembershipError):
        verified_google_claims(
            {
                "userinfo": {
                    "iss": "https://accounts.google.com",
                    "sub": "synthetic-subject",
                    "email": "oidc-user@example.invalid",
                    "email_verified": "true",
                }
            }
        )


def test_authenticated_landing_template_has_no_external_script_source() -> None:
    template = Path("app/templates/index.html").read_text(encoding="utf-8")

    assert "cdn.tailwindcss.com" not in template
    assert re.search(r'<script[^>]+src=["\']https?://', template, re.IGNORECASE) is None
