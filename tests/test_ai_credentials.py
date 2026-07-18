from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.models import AiConsultationDraft, AiProviderCredential
from app.services.ai_credentials import (
    ByokCredentialCipher,
    decrypt_provider_credential,
    delete_provider_credential,
    save_provider_credential,
)
from app.services.ai_drafts import (
    AiDraftError,
    confirm_ai_draft,
    create_ai_draft,
    reject_ai_draft,
)
from app.services.ai_narratives import generate_consultation_narrative
from app.services.ai_payloads import AnonymousConsultationPayload
from app.services.ai_providers import NarrativeDraft
from tests.test_ai_payloads import _result


@pytest.fixture
def session(postgres_engine: Engine) -> Iterator[Session]:
    connection = postgres_engine.connect()
    transaction = connection.begin()
    database_session = Session(bind=connection)
    try:
        yield database_session
    finally:
        database_session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def test_provider_key_is_encrypted_masked_replaced_and_deleted(session: Session) -> None:
    cipher = ByokCredentialCipher(Fernet.generate_key().decode("ascii"))

    saved = save_provider_credential(
        session,
        actor_ref="synthetic-admin",
        provider="OPENAI",
        api_key="synthetic-api-key-1234",
        cipher=cipher,
    )
    session.flush()

    assert "synthetic-api-key" not in saved.encrypted_api_key
    assert saved.masked_hint == "••••1234"
    assert decrypt_provider_credential(saved, cipher) == "synthetic-api-key-1234"

    replaced = save_provider_credential(
        session,
        actor_ref="synthetic-admin",
        provider="OPENAI",
        api_key="replacement-key-9999",
        cipher=cipher,
    )
    session.flush()

    assert replaced.id == saved.id
    assert decrypt_provider_credential(replaced, cipher) == "replacement-key-9999"
    delete_provider_credential(session, actor_ref="synthetic-admin", provider="OPENAI")
    session.flush()
    assert session.get(AiProviderCredential, saved.id) is None


def test_wrong_master_key_and_tampered_ciphertext_are_rejected(session: Session) -> None:
    cipher = ByokCredentialCipher(Fernet.generate_key().decode("ascii"))
    saved = save_provider_credential(
        session,
        actor_ref="synthetic-admin",
        provider="GEMINI",
        api_key="synthetic-gemini-key",
        cipher=cipher,
    )
    session.flush()

    wrong = ByokCredentialCipher(Fernet.generate_key().decode("ascii"))
    with pytest.raises(InvalidToken):
        decrypt_provider_credential(saved, wrong)
    saved.encrypted_api_key = saved.encrypted_api_key[:-1] + "A"
    with pytest.raises(InvalidToken):
        decrypt_provider_credential(saved, cipher)


def test_teacher_must_explicitly_confirm_an_owned_draft(session: Session) -> None:
    payload_data = {
        "schema_version": 2,
        "academic_year": 2027,
        "results": [
            {
                "item_status": "ELIGIBILITY_BLOCKED",
                "target": {
                    "academic_year": 2027,
                    "institution_name": "합성전문대",
                    "campus_name": "본교",
                    "program_name": "합성학과",
                    "admission_round_name": "수시 1차",
                    "admission_track_name": "일반고 전형",
                },
                "eligibility": {
                    "status": "INELIGIBLE",
                    "reason_code": "TRACK_NOT_ALLOWED",
                    "missing_fact_names": [],
                    "rule_version": "v1",
                },
                "average_grade": None,
                "admission_result": {"status": "NOT_AVAILABLE"},
                "evidence": [],
                "warnings": [],
            }
        ],
    }
    canonical_json = json.dumps(
        payload_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    payload = AnonymousConsultationPayload(
        schema_version=2,
        data=payload_data,
        canonical_json=canonical_json,
        digest=hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
    )
    record = create_ai_draft(
        session,
        actor_ref="synthetic-admin",
        provider="ANTHROPIC",
        model_name="synthetic-model",
        payload=payload,
        draft=NarrativeDraft(
            text="검증된 결과를 설명하는 합성 초안입니다.",
            check_items=("공식 자료를 다시 확인하세요.",),
        ),
    )
    session.flush()

    assert record.status == "GENERATED_DRAFT"
    assert record.teacher_text is None
    assert record.confirmed_at is None
    with pytest.raises(AiDraftError):
        confirm_ai_draft(
            session,
            draft_id=record.id,
            actor_ref="another-admin",
            teacher_text="다른 관리자의 문장",
            confirmed_at=datetime(2026, 7, 14, tzinfo=UTC),
        )

    confirmed = confirm_ai_draft(
        session,
        draft_id=record.id,
        actor_ref="synthetic-admin",
        teacher_text="교사가 검토하고 수정한 합성 상담 문장입니다.",
        confirmed_at=datetime(2026, 7, 14, tzinfo=UTC),
    )
    session.flush()

    assert confirmed.status == "TEACHER_CONFIRMED"
    assert confirmed.confirmed_by == "synthetic-admin"
    assert confirmed.payload_digest == payload.digest
    assert session.get(AiConsultationDraft, record.id) is confirmed


def test_teacher_can_reject_only_an_unconfirmed_owned_draft(session: Session) -> None:
    record = AiConsultationDraft(
        actor_ref="synthetic-admin",
        provider="OPENAI",
        model_name="synthetic-model",
        payload_schema_version=1,
        payload_digest="c" * 64,
        generated_text="사용하지 않을 합성 초안입니다.",
        check_items=[],
        status="GENERATED_DRAFT",
    )
    session.add(record)
    session.flush()

    rejected = reject_ai_draft(
        session,
        draft_id=record.id,
        actor_ref="synthetic-admin",
    )
    session.flush()

    assert rejected.status == "REJECTED"
    assert rejected.teacher_text is None
    with pytest.raises(AiDraftError):
        reject_ai_draft(session, draft_id=record.id, actor_ref="synthetic-admin")


def test_narrative_orchestration_uses_owned_key_and_anonymous_payload(session: Session) -> None:
    cipher = ByokCredentialCipher(Fernet.generate_key().decode("ascii"))
    save_provider_credential(
        session,
        actor_ref="synthetic-admin",
        provider="OPENAI",
        api_key="synthetic-provider-key-1234",
        cipher=cipher,
    )
    session.flush()

    class SyntheticOpenAiAdapter:
        provider_code = "OPENAI"

        def __init__(self) -> None:
            self.payload: dict[str, object] | None = None

        def generate(self, payload: dict[str, object], api_key: str) -> NarrativeDraft:
            assert api_key == "synthetic-provider-key-1234"
            self.payload = payload
            return NarrativeDraft(
                text="검증된 결과를 설명하는 합성 초안입니다.",
                check_items=("최종 모집요강을 확인하세요.",),
            )

    provider = SyntheticOpenAiAdapter()
    draft = generate_consultation_narrative(
        session,
        actor_ref="synthetic-admin",
        provider_code="OPENAI",
        model_name="synthetic-model",
        result=_result(),
        provider=provider,
        cipher=cipher,
    )
    session.flush()

    assert provider.payload is not None
    assert "student_id" not in provider.payload
    assert draft.status == "GENERATED_DRAFT"
    assert len(draft.payload_digest) == 64
    assert "synthetic-provider-key" not in draft.generated_text
