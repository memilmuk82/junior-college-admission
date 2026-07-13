from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.services.ai_payloads import AnonymousConsultationPayload, validated_payload_copy

PROVIDER_CODES = frozenset({"OPENAI", "GEMINI", "ANTHROPIC"})
FORBIDDEN_NARRATIVE_TERMS = (
    "합격확률",
    "합격가능",
    "불합격",
    "안정",
    "적정",
    "소신",
    "위험",
    "추천",
    "지원권장",
)
NUMERIC_TOKEN = re.compile(r"(?<![\d.])[-+]?\d+(?:\.\d+)?%?")


class NarrativeProviderError(ValueError):
    pass


@dataclass(frozen=True)
class NarrativeDraft:
    text: str
    check_items: tuple[str, ...]


class NarrativeProvider(Protocol):
    provider_code: str

    def generate(self, payload: dict[str, object], api_key: str) -> NarrativeDraft: ...


def generate_narrative_draft(
    provider: NarrativeProvider,
    payload: AnonymousConsultationPayload,
    api_key: str,
) -> NarrativeDraft:
    if not api_key or api_key != api_key.strip():
        raise NarrativeProviderError("유효한 공급자 API 키가 필요합니다.")
    try:
        provider_payload = validated_payload_copy(payload)
    except ValueError as error:
        raise NarrativeProviderError(str(error)) from error
    draft = provider.generate(provider_payload, api_key)
    validated = validate_narrative_draft(draft)
    _reject_ungrounded_numbers(validated, provider_payload)
    return validated


def validate_narrative_draft(draft: NarrativeDraft) -> NarrativeDraft:
    text = draft.text.strip()
    if not text or len(text) > 2000:
        raise NarrativeProviderError("상담 초안은 1자 이상 2000자 이하여야 합니다.")
    if len(draft.check_items) > 10:
        raise NarrativeProviderError("추가 확인 항목은 10개를 넘을 수 없습니다.")
    items = tuple(item.strip() for item in draft.check_items)
    if any(not item or len(item) > 300 for item in items):
        raise NarrativeProviderError("추가 확인 항목은 1자 이상 300자 이하여야 합니다.")
    combined = _compact_text("\n".join((text, *items)))
    found = next((term for term in FORBIDDEN_NARRATIVE_TERMS if term in combined), None)
    if found is not None:
        raise NarrativeProviderError(f"AI 상담 초안에 금지 표현이 포함되어 있습니다: {found}")
    return NarrativeDraft(text=text, check_items=items)


def _compact_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return "".join(
        character
        for character in normalized
        if not character.isspace() and unicodedata.category(character) != "Cf"
    )


def _reject_ungrounded_numbers(draft: NarrativeDraft, payload: dict[str, object]) -> None:
    allowed = _payload_numbers(payload)
    for token in NUMERIC_TOKEN.findall("\n".join((draft.text, *draft.check_items))):
        is_percent = token.endswith("%")
        try:
            value = Decimal(token.removesuffix("%"))
        except InvalidOperation as error:
            raise NarrativeProviderError("AI 상담 초안의 숫자 형식이 유효하지 않습니다.") from error
        candidates = {value, value.normalize()}
        if is_percent:
            candidates.add((value / Decimal(100)).normalize())
        if allowed.isdisjoint(candidates):
            raise NarrativeProviderError(
                "AI 상담 초안에 입력 근거가 없는 숫자가 포함되어 있습니다."
            )


def _payload_numbers(value: object) -> set[Decimal]:
    numbers: set[Decimal] = set()
    if isinstance(value, bool) or value is None:
        return numbers
    if isinstance(value, int | Decimal):
        return {Decimal(value).normalize()}
    if isinstance(value, str):
        try:
            return {Decimal(value).normalize()}
        except InvalidOperation:
            return numbers
    if isinstance(value, dict):
        for item in value.values():
            numbers.update(_payload_numbers(item))
    elif isinstance(value, list):
        for item in value:
            numbers.update(_payload_numbers(item))
    return numbers


__all__ = [
    "FORBIDDEN_NARRATIVE_TERMS",
    "NarrativeDraft",
    "NarrativeProvider",
    "NarrativeProviderError",
    "PROVIDER_CODES",
    "generate_narrative_draft",
    "validate_narrative_draft",
]
