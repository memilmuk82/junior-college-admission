from __future__ import annotations

import json
import os
import ssl
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

OPERATIONS_USER_AGENT = "junior-college-admission-operations/1.0"


def main() -> int:
    base_url = os.environ.get("PRODUCTION_URL", "")
    ca_file = os.environ.get("PRODUCTION_CA_CERT", "")
    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.hostname or not Path(ca_file).is_file():
        print("운영 HTTPS 검사 실패: PRODUCTION_URL, PRODUCTION_CA_CERT")
        return 1

    context = ssl.create_default_context(cafile=ca_file)
    health_url = urljoin(base_url.rstrip("/") + "/", "health")
    request = Request(
        health_url,
        headers={"Accept": "application/json", "User-Agent": OPERATIONS_USER_AGENT},
        method="GET",
    )
    try:
        with urlopen(request, context=context, timeout=10) as response:  # noqa: S310
            payload = json.load(response)
            headers = response.headers
            status = response.status
    except (OSError, ValueError, json.JSONDecodeError):
        print("운영 HTTPS 검사 실패: TLS 또는 health 응답")
        return 1

    expected_headers = {
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "X-Frame-Options": "DENY",
    }
    if (
        status != 200
        or payload != {"service": "junior-college-admission", "status": "ok"}
        or any(headers.get(name) != value for name, value in expected_headers.items())
    ):
        print("운영 HTTPS 검사 실패: health 또는 보안 헤더")
        return 1
    print("운영 HTTPS 검사 통과: TLS, health, 보안 헤더를 확인했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
