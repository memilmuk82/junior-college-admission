from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlencode

import pytest

from scripts.check_google_oidc_https import main, valid_google_authorization_redirect


def _make_target(name: str) -> str:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(name)}:\n(?P<body>(?:\t.*\n)+)",
        makefile,
        re.MULTILINE,
    )
    assert match is not None
    return match.group("body")


def test_oidc_enable_requires_independent_change_window_attestations() -> None:
    target = _make_target("production-origin-oidc-up")

    assert 'test "$(OIDC_CHANGE_APPROVED)" = "APPROVED"' in target
    assert 'test "$(OIDC_HOST_GATE_CONFIRMED)" = "PASSED"' in target
    assert 'test "$(OIDC_BACKUP_RESTORE_CONFIRMED)" = "VERIFIED"' in target
    assert target.count("-f docker-compose.google-oidc.yml") == 4
    assert target.index("config --quiet") < target.index("build web-production")
    assert target.index("build web-production") < target.index(
        "run --rm --no-deps web-production python -c"
    )
    assert 'app.config["GOOGLE_OIDC_ENABLED"] is True' in target
    assert target.index("run --rm --no-deps") < target.index(
        "up -d --no-build --wait web-production"
    )
    assert "GOOGLE_OIDC_CLIENT_SECRET" not in target


def test_oidc_status_and_check_use_the_exact_enabled_compose_profile() -> None:
    status = _make_target("production-origin-oidc-status")
    check = _make_target("production-origin-oidc-check")

    assert "-f docker-compose.google-oidc.yml" in status
    assert "-f docker-compose.google-oidc.yml" in check
    assert "scripts.check_production_https" in check
    assert "scripts.check_google_oidc_https" in check
    assert "flask --app wsgi db current" in check


def test_oidc_disable_forces_false_without_the_enabled_override_or_rebuild() -> None:
    target = _make_target("production-origin-oidc-disable")

    assert 'test "$(OIDC_CHANGE_APPROVED)" = "APPROVED"' in target
    assert target.count("GOOGLE_OIDC_ENABLED=false") == 2
    assert "docker-compose.google-oidc.yml" not in target
    assert "--no-build --no-deps --force-recreate --wait web-production" in target
    assert " build " not in target


def test_google_authorization_redirect_contract_accepts_no_secret_output_needed() -> None:
    callback = "https://service.example.test/auth/google/callback"
    query = urlencode(
        {
            "client_id": "synthetic-client-id",
            "redirect_uri": callback,
            "response_type": "code",
            "scope": "openid email profile",
            "state": "synthetic-state",
            "nonce": "synthetic-nonce",
            "code_challenge": "synthetic-code-challenge",
            "code_challenge_method": "S256",
        }
    )

    assert valid_google_authorization_redirect(
        f"https://accounts.google.com/o/oauth2/v2/auth?{query}", callback
    )


def test_google_authorization_redirect_contract_rejects_untrusted_or_weakened_values() -> None:
    callback = "https://service.example.test/auth/google/callback"
    base_query = {
        "client_id": "synthetic-client-id",
        "redirect_uri": callback,
        "response_type": "code",
        "scope": "openid email profile",
        "state": "synthetic-state",
        "nonce": "synthetic-nonce",
        "code_challenge": "synthetic-code-challenge",
        "code_challenge_method": "S256",
    }

    for authority, changes in (
        ("attacker.example.test", {}),
        ("accounts.google.com", {"redirect_uri": "https://attacker.example.test/callback"}),
        ("accounts.google.com", {"code_challenge_method": "plain"}),
        ("accounts.google.com", {"state": ""}),
    ):
        query = urlencode(base_query | changes)
        location = f"https://{authority}/o/oauth2/v2/auth?{query}"
        assert not valid_google_authorization_redirect(location, callback)


def test_google_oidc_https_check_never_prints_redirect_query_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    callback = "https://service.example.test/auth/google/callback"
    sensitive_values = {
        "client_id": "synthetic-client-id-must-not-print",
        "state": "synthetic-state-must-not-print",
        "nonce": "synthetic-nonce-must-not-print",
        "code_challenge": "synthetic-challenge-must-not-print",
    }
    query = urlencode(
        sensitive_values
        | {
            "redirect_uri": callback,
            "response_type": "code",
            "scope": "openid email profile",
            "code_challenge_method": "S256",
        }
    )
    certificate = tmp_path / "ca.pem"
    certificate.write_text("synthetic-ca", encoding="utf-8")

    class SyntheticResponse:
        status = 302

        def getheader(self, name: str, default: str = "") -> str:
            assert name == "Location"
            return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

    class SyntheticConnection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def request(
            self, method: str, target: str, headers: dict[str, str]
        ) -> None:
            assert method == "GET"
            assert target == "/auth/google/start"
            assert headers == {
                "Accept": "text/html",
                "User-Agent": "junior-college-admission-operations/1.0",
            }

        def getresponse(self) -> SyntheticResponse:
            return SyntheticResponse()

        def close(self) -> None:
            pass

    monkeypatch.setenv("PRODUCTION_URL", "https://service.example.test")
    monkeypatch.setenv("PRODUCTION_CA_CERT", str(certificate))
    monkeypatch.setattr(
        "scripts.check_google_oidc_https.ssl.create_default_context", lambda **_kwargs: object()
    )
    monkeypatch.setattr("scripts.check_google_oidc_https.HTTPSConnection", SyntheticConnection)

    assert main() == 0
    output = capsys.readouterr().out
    assert "검사 통과" in output
    assert all(value not in output for value in sensitive_values.values())


def test_phase_11_runbook_keeps_oidc_opt_in_and_orders_database_safety_gates() -> None:
    runbook = Path("docs/PHASE_11_OPERATIONS.md").read_text(encoding="utf-8")

    assert runbook.index("production-preflight") < runbook.index("production-origin-backup")
    assert runbook.index("production-origin-backup") < runbook.index(
        "production-origin-backup-verify"
    )
    assert runbook.index("production-origin-backup-verify") < runbook.index(
        "production-origin-restore-verify"
    )
    assert runbook.index("production-origin-restore-verify") < runbook.index(
        "production-origin-oidc-up"
    )
    assert "OIDC_HOST_GATE_CONFIRMED=PASSED" in runbook
    assert "OIDC_BACKUP_RESTORE_CONFIRMED=VERIFIED" in runbook
    assert "RESTORED_AND_VERIFIED" in runbook
    assert "image-only rollback" in runbook
