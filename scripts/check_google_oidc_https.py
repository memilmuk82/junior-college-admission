from __future__ import annotations

import os
import ssl
from http.client import HTTPException, HTTPSConnection
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

OPERATIONS_USER_AGENT = "junior-college-admission-operations/1.0"


def valid_google_authorization_redirect(location: str, expected_callback: str) -> bool:
    parsed = urlparse(location)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "accounts.google.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path != "/o/oauth2/v2/auth"
        or parsed.fragment
    ):
        return False

    query = parse_qs(parsed.query, keep_blank_values=True)
    required_exact = {
        "redirect_uri": expected_callback,
        "response_type": "code",
        "code_challenge_method": "S256",
    }
    if any(query.get(name) != [value] for name, value in required_exact.items()):
        return False
    for name in ("client_id", "state", "nonce", "code_challenge"):
        values = query.get(name)
        if values is None or len(values) != 1 or not values[0]:
            return False
    scope_values = query.get("scope")
    if scope_values is None or len(scope_values) != 1:
        return False
    scopes = set(scope_values[0].split())
    return {"openid", "email", "profile"}.issubset(scopes)


def main() -> int:
    base_url = os.environ.get("PRODUCTION_URL", "")
    ca_file = os.environ.get("PRODUCTION_CA_CERT", "")
    parsed = urlparse(base_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
        or not Path(ca_file).is_file()
    ):
        print("Google OIDC HTTPS 검사 실패: PRODUCTION_URL, PRODUCTION_CA_CERT")
        return 1

    try:
        context = ssl.create_default_context(cafile=ca_file)
    except (OSError, ValueError):
        print("Google OIDC HTTPS 검사 실패: PRODUCTION_CA_CERT")
        return 1
    start_path = urlparse(urljoin(base_url.rstrip("/") + "/", "auth/google/start"))
    expected_callback = urljoin(base_url.rstrip("/") + "/", "auth/google/callback")
    connection = HTTPSConnection(
        parsed.hostname,
        parsed.port,
        context=context,
        timeout=10,
    )
    try:
        connection.request(
            "GET",
            start_path.path,
            headers={"Accept": "text/html", "User-Agent": OPERATIONS_USER_AGENT},
        )
        response = connection.getresponse()
        status = response.status
        location = response.getheader("Location", "")
    except (HTTPException, OSError, ValueError):
        print("Google OIDC HTTPS 검사 실패: 시작 endpoint 응답")
        return 1
    finally:
        connection.close()

    if status not in {302, 303} or not valid_google_authorization_redirect(
        location, expected_callback
    ):
        print("Google OIDC HTTPS 검사 실패: authorization redirect 계약")
        return 1
    print("Google OIDC HTTPS 검사 통과: 비밀 쿼리값을 출력하지 않고 redirect를 확인했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
