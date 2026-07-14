from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.services.ai_providers import (
    NarrativeDraft,
    NarrativeProvider,
    NarrativeProviderError,
)

REQUEST_TIMEOUT_SECONDS = 15.0
MAX_REQUEST_BYTES = 64 * 1024
MAX_RESPONSE_BYTES = 128 * 1024
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")

SYSTEM_INSTRUCTION = """당신은 전문대 입시 상담 교사를 돕는 문장 작성 도구입니다.
제공된 JSON의 검증된 사실만 자연스러운 한국어로 다시 설명하세요.
지원자격이나 점수를 새로 계산하거나 변경하지 마세요.
합격 가능성, 불합격, 안정·적정·소신·위험 판단, 대학·학과 추천을 작성하지 마세요.
학생 개인정보를 추정하거나 요구하지 마세요.
근거가 부족한 내용은 check_items에 확인 항목으로만 적으세요.
draft_text와 check_items 어디에도 다음 문자열을 그대로 쓰지 마세요:
합격확률, 합격가능, 불합격, 안정, 적정, 소신, 위험, 추천, 지원권장.
반드시 지정된 JSON 스키마만 출력하세요."""

DRAFT_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "draft_text": {"type": "string", "minLength": 1, "maxLength": 2000},
        "check_items": {
            "type": "array",
            "maxItems": 10,
            "items": {"type": "string", "minLength": 1, "maxLength": 300},
        },
    },
    "required": ["draft_text", "check_items"],
}


class ProviderHttpError(NarrativeProviderError):
    """External provider failure whose message is safe for an administrator."""


class JsonHttpTransport(Protocol):
    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]: ...


class UrllibJsonTransport:
    """Small bounded JSON transport with no implicit retries or secret logging."""

    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_REQUEST_BYTES:
            raise ProviderHttpError("외부 공급자 요청 크기 제한을 초과했습니다.")
        request = Request(
            url,
            data=encoded,
            headers={"Accept": "application/json", **headers},
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
                content_type = response.headers.get_content_type().lower()
                if content_type != "application/json" and not content_type.endswith("+json"):
                    raise ProviderHttpError("외부 공급자가 JSON이 아닌 응답을 반환했습니다.")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            raise ProviderHttpError(
                f"외부 공급자 요청이 실패했습니다(HTTP {error.code})."
            ) from None
        except (URLError, TimeoutError, OSError):
            raise ProviderHttpError("외부 공급자에 연결할 수 없습니다.") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ProviderHttpError("외부 공급자 응답 크기 제한을 초과했습니다.")
        try:
            decoded = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProviderHttpError("외부 공급자 JSON 응답을 해석할 수 없습니다.") from None
        if not isinstance(decoded, dict) or not all(isinstance(key, str) for key in decoded):
            raise ProviderHttpError("외부 공급자 응답 구조가 올바르지 않습니다.")
        return decoded


@dataclass(frozen=True)
class _BaseNarrativeProvider:
    model_name: str
    transport: JsonHttpTransport

    def __init__(
        self,
        model_name: str,
        *,
        transport: JsonHttpTransport | None = None,
    ) -> None:
        if not MODEL_NAME.fullmatch(model_name):
            raise NarrativeProviderError("공급자 모델 이름 형식이 올바르지 않습니다.")
        object.__setattr__(self, "model_name", model_name)
        object.__setattr__(self, "transport", transport or UrllibJsonTransport())

    def _post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        body: dict[str, object],
    ) -> dict[str, object]:
        try:
            return self.transport.post_json(
                url,
                headers={"Content-Type": "application/json", **headers},
                payload=body,
                timeout_seconds=REQUEST_TIMEOUT_SECONDS,
            )
        except ProviderHttpError:
            raise
        except Exception:
            raise ProviderHttpError("외부 공급자 요청이 실패했습니다.") from None


class OpenAiNarrativeProvider(_BaseNarrativeProvider):
    provider_code = "OPENAI"

    def generate(self, payload: dict[str, object], api_key: str) -> NarrativeDraft:
        body: dict[str, object] = {
            "model": self.model_name,
            "instructions": SYSTEM_INSTRUCTION,
            "input": _payload_text(payload),
            # Reasoning models consume part of this budget before emitting JSON.
            "max_output_tokens": 4096,
            "store": False,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "consultation_narrative_draft",
                    "strict": True,
                    "schema": DRAFT_SCHEMA,
                }
            },
        }
        response = self._post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}"},
            body=body,
        )
        return _decode_draft(_openai_output_text(response))


class GeminiNarrativeProvider(_BaseNarrativeProvider):
    provider_code = "GEMINI"

    def generate(self, payload: dict[str, object], api_key: str) -> NarrativeDraft:
        body: dict[str, object] = {
            "systemInstruction": {"parts": [{"text": SYSTEM_INSTRUCTION}]},
            "contents": [{"role": "user", "parts": [{"text": _payload_text(payload)}]}],
            "generationConfig": {
                "candidateCount": 1,
                "maxOutputTokens": 1200,
                "responseMimeType": "application/json",
                "responseJsonSchema": DRAFT_SCHEMA,
            },
        }
        response = self._post(
            "https://generativelanguage.googleapis.com/"
            f"v1beta/models/{self.model_name}:generateContent",
            headers={"x-goog-api-key": api_key},
            body=body,
        )
        return _decode_draft(_gemini_output_text(response))


class AnthropicNarrativeProvider(_BaseNarrativeProvider):
    provider_code = "ANTHROPIC"

    def generate(self, payload: dict[str, object], api_key: str) -> NarrativeDraft:
        body: dict[str, object] = {
            "model": self.model_name,
            "max_tokens": 1200,
            "system": SYSTEM_INSTRUCTION,
            "messages": [{"role": "user", "content": _payload_text(payload)}],
            "output_config": {"format": {"type": "json_schema", "schema": DRAFT_SCHEMA}},
        }
        response = self._post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            body=body,
        )
        return _decode_draft(_anthropic_output_text(response))


def provider_adapter(
    provider_code: str,
    model_name: str,
    *,
    transport: JsonHttpTransport | None = None,
) -> NarrativeProvider:
    adapters: dict[str, type[_BaseNarrativeProvider]] = {
        "OPENAI": OpenAiNarrativeProvider,
        "GEMINI": GeminiNarrativeProvider,
        "ANTHROPIC": AnthropicNarrativeProvider,
    }
    adapter_type = adapters.get(provider_code)
    if adapter_type is None:
        raise NarrativeProviderError("지원하지 않는 외부 AI 공급자입니다.")
    return cast(NarrativeProvider, adapter_type(model_name, transport=transport))


def _payload_text(payload: dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _decode_draft(value: str) -> NarrativeDraft:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        raise NarrativeProviderError("외부 공급자 초안 JSON을 해석할 수 없습니다.") from None
    if not isinstance(decoded, dict) or set(decoded) != {"draft_text", "check_items"}:
        raise NarrativeProviderError("외부 공급자 초안 구조가 올바르지 않습니다.")
    text = decoded["draft_text"]
    items = decoded["check_items"]
    if (
        not isinstance(text, str)
        or not isinstance(items, list)
        or not all(isinstance(item, str) for item in items)
    ):
        raise NarrativeProviderError("외부 공급자 초안 필드 형식이 올바르지 않습니다.")
    return NarrativeDraft(text=text, check_items=tuple(items))


def _openai_output_text(response: dict[str, object]) -> str:
    if response.get("status") != "completed":
        raise NarrativeProviderError("OpenAI 응답이 정상 완료되지 않았습니다.")
    top_level = response.get("output_text")
    if isinstance(top_level, str):
        return top_level
    output = response.get("output")
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "message":
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") == "output_text"
                    and isinstance(part.get("text"), str)
                ):
                    return part["text"]
    raise NarrativeProviderError("OpenAI 응답에 상담 초안이 없습니다.")


def _gemini_output_text(response: dict[str, object]) -> str:
    candidates = response.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise NarrativeProviderError("Gemini 응답에 단일 상담 초안이 없습니다.")
    candidate = candidates[0]
    if not isinstance(candidate, dict) or candidate.get("finishReason", "STOP") != "STOP":
        raise NarrativeProviderError("Gemini 응답이 정상 완료되지 않았습니다.")
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if isinstance(parts, list):
        text_parts = [
            part["text"]
            for part in parts
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ]
        if text_parts:
            return "".join(text_parts)
    raise NarrativeProviderError("Gemini 응답에 상담 초안이 없습니다.")


def _anthropic_output_text(response: dict[str, object]) -> str:
    if response.get("stop_reason", "end_turn") != "end_turn":
        raise NarrativeProviderError("Anthropic 응답이 정상 완료되지 않았습니다.")
    content = response.get("content")
    if isinstance(content, list):
        text_parts = [
            part["text"]
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        ]
        if text_parts:
            return "".join(text_parts)
    raise NarrativeProviderError("Anthropic 응답에 상담 초안이 없습니다.")


__all__ = [
    "AnthropicNarrativeProvider",
    "GeminiNarrativeProvider",
    "JsonHttpTransport",
    "OpenAiNarrativeProvider",
    "ProviderHttpError",
    "UrllibJsonTransport",
    "provider_adapter",
]
