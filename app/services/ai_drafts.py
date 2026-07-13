from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import AiConsultationDraft
from app.services.ai_payloads import AnonymousConsultationPayload, validated_payload_copy
from app.services.ai_providers import (
    PROVIDER_CODES,
    NarrativeDraft,
    validate_narrative_draft,
)


class AiDraftError(ValueError):
    pass


def create_ai_draft(
    session: Session,
    *,
    actor_ref: str,
    provider: str,
    model_name: str,
    payload: AnonymousConsultationPayload,
    draft: NarrativeDraft,
) -> AiConsultationDraft:
    _validate_actor(actor_ref)
    if provider not in PROVIDER_CODES:
        raise AiDraftError("지원하지 않는 AI 공급자입니다.")
    model_name = model_name.strip()
    if not model_name or len(model_name) > 120:
        raise AiDraftError("모델 이름은 1자 이상 120자 이하여야 합니다.")
    try:
        validated_payload_copy(payload)
    except ValueError as error:
        raise AiDraftError(str(error)) from error
    validated = validate_narrative_draft(draft)
    record = AiConsultationDraft(
        actor_ref=actor_ref,
        provider=provider,
        model_name=model_name,
        payload_schema_version=payload.schema_version,
        payload_digest=payload.digest,
        generated_text=validated.text,
        check_items=list(validated.check_items),
        status="GENERATED_DRAFT",
    )
    session.add(record)
    return record


def confirm_ai_draft(
    session: Session,
    *,
    draft_id: str,
    actor_ref: str,
    teacher_text: str,
    confirmed_at: datetime,
) -> AiConsultationDraft:
    _validate_actor(actor_ref)
    record = session.get(AiConsultationDraft, draft_id)
    if record is None:
        raise AiDraftError("AI 상담 초안을 찾을 수 없습니다.")
    if record.actor_ref != actor_ref:
        raise AiDraftError("다른 관리자의 AI 상담 초안을 확정할 수 없습니다.")
    if record.status != "GENERATED_DRAFT":
        raise AiDraftError("생성된 미확정 초안만 확정할 수 있습니다.")
    validated = validate_narrative_draft(NarrativeDraft(teacher_text, ()))
    if confirmed_at.tzinfo is None:
        raise AiDraftError("확정 시각에는 시간대가 필요합니다.")
    record.teacher_text = validated.text
    record.status = "TEACHER_CONFIRMED"
    record.confirmed_by = actor_ref
    record.confirmed_at = confirmed_at
    return record


def reject_ai_draft(
    session: Session,
    *,
    draft_id: str,
    actor_ref: str,
) -> AiConsultationDraft:
    _validate_actor(actor_ref)
    record = session.get(AiConsultationDraft, draft_id)
    if record is None:
        raise AiDraftError("AI 상담 초안을 찾을 수 없습니다.")
    if record.actor_ref != actor_ref:
        raise AiDraftError("다른 관리자의 AI 상담 초안을 거부할 수 없습니다.")
    if record.status != "GENERATED_DRAFT":
        raise AiDraftError("생성된 미확정 초안만 거부할 수 있습니다.")
    record.status = "REJECTED"
    return record


def _validate_actor(actor_ref: str) -> None:
    if not actor_ref or actor_ref != actor_ref.strip() or len(actor_ref) > 120:
        raise AiDraftError("관리자 식별자가 유효하지 않습니다.")


__all__ = ["AiDraftError", "confirm_ai_draft", "create_ai_draft", "reject_ai_draft"]
