from __future__ import annotations

from email.message import Message
from pathlib import Path
from urllib.request import Request

import pytest

from scripts.check_production_https import main


def test_https_check_uses_an_explicit_operations_user_agent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    certificate = tmp_path / "ca.pem"
    certificate.write_text("synthetic-ca", encoding="utf-8")
    headers = Message()
    headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    headers["X-Content-Type-Options"] = "nosniff"
    headers["Referrer-Policy"] = "no-referrer"
    headers["X-Frame-Options"] = "DENY"

    class SyntheticResponse:
        status = 200

        def __init__(self) -> None:
            self.headers = headers

        def __enter__(self) -> SyntheticResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _size: int = -1) -> bytes:
            return b'{"service":"junior-college-admission","status":"ok"}'

    def synthetic_urlopen(
        request: Request, *, context: object, timeout: int
    ) -> SyntheticResponse:
        assert request.full_url == "https://service.example.test/health"
        assert request.get_method() == "GET"
        assert request.get_header("User-agent") == (
            "junior-college-admission-operations/1.0"
        )
        assert request.get_header("Accept") == "application/json"
        assert context is not None
        assert timeout == 10
        return SyntheticResponse()

    monkeypatch.setenv("PRODUCTION_URL", "https://service.example.test")
    monkeypatch.setenv("PRODUCTION_CA_CERT", str(certificate))
    monkeypatch.setattr(
        "scripts.check_production_https.ssl.create_default_context",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr("scripts.check_production_https.urlopen", synthetic_urlopen)

    assert main() == 0
    assert "검사 통과" in capsys.readouterr().out
