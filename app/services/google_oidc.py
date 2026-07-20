from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from authlib.integrations.flask_client import OAuth
from flask import Flask, current_app, redirect, session, url_for

from app.services.membership import MembershipError, canonicalize_google_issuer

GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
GOOGLE_SCOPE = "openid email profile"
AUTHLIB_CLIENT_LOGGER = "authlib.integrations.base_client"
DEMO_GOOGLE_CLAIMS_SESSION_KEY = "demo_google_verified_claims"


class DemoGoogleOidcClient:
    """Same-origin OIDC stand-in available only in the isolated demo app."""

    def authorize_redirect(self, _redirect_uri: str):  # type: ignore[no-untyped-def]
        return redirect(url_for("auth.google_demo_consent"), code=303)

    def authorize_access_token(self) -> Mapping[str, Any]:
        token = session.pop(DEMO_GOOGLE_CLAIMS_SESSION_KEY, None)
        if not isinstance(token, Mapping):
            raise MembershipError("Google 체험 승인을 확인할 수 없습니다.")
        return token


def init_google_oidc(app: Flask) -> None:
    if app.config.get("DEMO_GOOGLE_STUB_ENABLED"):
        if app.config.get("DEMO_SANDBOX_ENABLED") is not True:
            raise RuntimeError("Google 체험 연결은 격리 체험 환경에서만 사용할 수 있습니다.")
        app.extensions["google_oidc"] = None
        app.extensions["google_oidc_client"] = DemoGoogleOidcClient()
        return
    if not app.config.get("GOOGLE_OIDC_ENABLED"):
        app.extensions["google_oidc_client"] = None
        return
    client_id = app.config.get("GOOGLE_OIDC_CLIENT_ID")
    client_secret = app.config.get("GOOGLE_OIDC_CLIENT_SECRET")
    if not isinstance(client_id, str) or not client_id:
        raise RuntimeError("Google OIDC 설정이 누락되었습니다: GOOGLE_OIDC_CLIENT_ID")
    if not isinstance(client_secret, str) or not client_secret:
        raise RuntimeError("Google OIDC 설정이 누락되었습니다: GOOGLE_OIDC_CLIENT_SECRET")
    # Authlib의 DEBUG 로그에는 PKCE code_verifier가 포함될 수 있다. 애플리케이션의
    # 전역 로그 레벨과 무관하게 OAuth 일회성 비밀값이 로그로 흘러나오지 않게 한다.
    logging.getLogger(AUTHLIB_CLIENT_LOGGER).setLevel(logging.WARNING)
    oauth = OAuth(app)
    client = oauth.register(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=GOOGLE_DISCOVERY_URL,
        client_kwargs={"scope": GOOGLE_SCOPE, "code_challenge_method": "S256"},
    )
    app.extensions["google_oidc"] = oauth
    app.extensions["google_oidc_client"] = client


def google_oidc_client() -> Any:
    client = current_app.extensions.get("google_oidc_client")
    if client is None:
        raise MembershipError("Google 로그인이 현재 활성화되지 않았습니다.")
    return client


def verified_google_claims(token: Mapping[str, Any]) -> dict[str, str | bool]:
    userinfo = token.get("userinfo")
    if not isinstance(userinfo, Mapping):
        raise MembershipError("Google 사용자 정보를 검증할 수 없습니다.")
    issuer = userinfo.get("iss")
    subject = userinfo.get("sub")
    email = userinfo.get("email")
    email_verified = userinfo.get("email_verified")
    display_name = userinfo.get("name") or email
    if not isinstance(issuer, str):
        raise MembershipError("Google 발급자를 확인할 수 없습니다.")
    canonical_issuer = canonicalize_google_issuer(issuer)
    if not isinstance(subject, str) or not subject:
        raise MembershipError("Google 사용자 식별자를 확인할 수 없습니다.")
    if not isinstance(email, str) or not email:
        raise MembershipError("Google 이메일을 확인할 수 없습니다.")
    if email_verified is not True:
        raise MembershipError("검증된 Google 이메일만 사용할 수 있습니다.")
    if not isinstance(display_name, str) or not display_name.strip():
        raise MembershipError("Google 표시 이름을 확인할 수 없습니다.")
    return {
        "issuer": canonical_issuer,
        "subject": subject,
        "email": email,
        "email_verified": True,
        "display_name": display_name,
    }
