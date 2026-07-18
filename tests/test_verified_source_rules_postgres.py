from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from app import create_app
from app.models import UserAccount, UserAccountAuditEvent, VerifiedSourceRuleConfirmation
from app.services.membership import bootstrap_admin
from app.services.verified_source_rules import find_verified_source_rule


def test_admin_confirms_verified_json_rule_and_digest_is_persisted(
    postgres_engine: Engine,
) -> None:
    admin_id = ""
    try:
        with Session(postgres_engine, expire_on_commit=False) as database_session:
            admin = bootstrap_admin(
                database_session,
                login_name="phase14-rule-confirm-admin",
                password_hash="synthetic-password-hash",
                occurred_at=datetime.now(UTC),
            )
            database_session.commit()
            admin_id = admin.id

        app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-only-secret",
                "DATABASE_URL": postgres_engine.url.render_as_string(hide_password=False),
            }
        )
        client = app.test_client()
        with client.session_transaction() as browser_session:
            browser_session["user_id"] = admin.id
            browser_session["auth_version"] = admin.auth_version
            browser_session["csrf_token"] = "phase14-rule-confirm-csrf"
            browser_session["admin_csrf_token"] = "phase14-rule-confirm-csrf"

        page = client.get("/admin/verified-source-rules")
        assert page.status_code == 200
        assert "동양미래_1. 2027학년도 수시 모집요강.pdf" in page.get_data(as_text=True)
        rule = find_verified_source_rule(
            academic_year=2027,
            institution_code="DONGYANG-MIRAE",
            campus_code="MAIN",
            admission_round_code="SUSI-1",
            admission_track_code="SPECIAL-GENERAL-HS",
        )
        assert rule is not None
        confirmed = client.post(
            f"/admin/verified-source-rules/{rule.rule_id}/{rule.version}/confirm",
            data={"csrf_token": "phase14-rule-confirm-csrf"},
        )
        assert confirmed.status_code == 302

        with Session(postgres_engine) as database_session:
            stored = database_session.scalar(
                select(VerifiedSourceRuleConfirmation).where(
                    VerifiedSourceRuleConfirmation.rule_id == rule.rule_id
                )
            )
            assert stored is not None
            assert stored.confirmed_by_user_account_id == admin.id
            assert len(stored.source_digest) == 64
    finally:
        if admin_id:
            with Session(postgres_engine) as database_session:
                database_session.execute(
                    delete(VerifiedSourceRuleConfirmation).where(
                        VerifiedSourceRuleConfirmation.confirmed_by_user_account_id == admin_id
                    )
                )
                database_session.execute(
                    delete(UserAccountAuditEvent).where(
                        (UserAccountAuditEvent.target_user_id == admin_id)
                        | (UserAccountAuditEvent.actor_user_id == admin_id)
                    )
                )
                database_session.execute(delete(UserAccount).where(UserAccount.id == admin_id))
                database_session.commit()
