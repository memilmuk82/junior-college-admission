from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AiConsultationDraft, AiProviderCredential
from app.services.ai_credentials import ByokCredentialCipher, decrypt_provider_credential
from app.services.ai_drafts import create_ai_draft
from app.services.ai_payloads import build_anonymous_consultation_payload
from app.services.ai_providers import (
    PROVIDER_CODES,
    NarrativeProvider,
    NarrativeProviderError,
    generate_narrative_draft,
)
from app.services.consultations import ConsultationResult


class AiNarrativeError(ValueError):
    pass


def generate_consultation_narrative(
    session: Session,
    *,
    actor_ref: str,
    provider_code: str,
    model_name: str,
    result: ConsultationResult,
    provider: NarrativeProvider,
    cipher: ByokCredentialCipher,
) -> AiConsultationDraft:
    if provider_code not in PROVIDER_CODES or provider.provider_code != provider_code:
        raise AiNarrativeError("요청 공급자와 등록된 어댑터가 일치하지 않습니다.")
    credential = session.scalar(
        select(AiProviderCredential).where(
            AiProviderCredential.actor_ref == actor_ref,
            AiProviderCredential.provider == provider_code,
        )
    )
    if credential is None:
        raise AiNarrativeError("현재 관리자에게 등록된 공급자 키가 없습니다.")
    payload = build_anonymous_consultation_payload(result)
    api_key = decrypt_provider_credential(credential, cipher)
    try:
        draft = generate_narrative_draft(provider, payload, api_key)
    except NarrativeProviderError as error:
        raise AiNarrativeError(str(error)) from error
    return create_ai_draft(
        session,
        actor_ref=actor_ref,
        provider=provider_code,
        model_name=model_name,
        payload=payload,
        draft=draft,
    )


__all__ = ["AiNarrativeError", "generate_consultation_narrative"]
