from __future__ import annotations

import json
from email.message import Message
from urllib.error import HTTPError

import pytest

from app.services.ai_http_providers import (
    MAX_REQUEST_BYTES,
    MAX_RESPONSE_BYTES,
    AnthropicNarrativeProvider,
    GeminiNarrativeProvider,
    OpenAiNarrativeProvider,
    ProviderHttpError,
    UrllibJsonTransport,
    provider_adapter,
)
from app.services.ai_payloads import build_anonymous_consultation_payload
from app.services.ai_providers import NarrativeProviderError, generate_narrative_draft
from tests.test_ai_payloads import _result


class RecordingTransport:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, str], dict[str, object], float]] = []

    def post_json(
        self,
        url: str,
        *,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        self.calls.append((url, headers, payload, timeout_seconds))
        return self.response


def _draft_json() -> str:
    return json.dumps(
        {
            "draft_text": "검증된 상담 결과를 근거 범위 안에서 요약했습니다.",
            "check_items": ["공식 근거와 최신 모집요강을 다시 확인하세요."],
        },
        ensure_ascii=False,
    )


@pytest.mark.parametrize(
    ("provider", "expected_url", "secret_header"),
    [
        (
            OpenAiNarrativeProvider,
            "https://api.openai.com/v1/responses",
            "Authorization",
        ),
        (
            GeminiNarrativeProvider,
            "https://generativelanguage.googleapis.com/v1beta/models/synthetic-model:generateContent",
            "x-goog-api-key",
        ),
        (
            AnthropicNarrativeProvider,
            "https://api.anthropic.com/v1/messages",
            "x-api-key",
        ),
    ],
)
def test_provider_requests_use_fixed_https_endpoints_and_header_only_keys(
    provider: type[OpenAiNarrativeProvider | GeminiNarrativeProvider | AnthropicNarrativeProvider],
    expected_url: str,
    secret_header: str,
) -> None:
    response: dict[str, object]
    if provider is OpenAiNarrativeProvider:
        response = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": _draft_json()}],
                }
            ],
        }
    elif provider is GeminiNarrativeProvider:
        response = {
            "candidates": [
                {"content": {"parts": [{"text": _draft_json()}]}, "finishReason": "STOP"}
            ]
        }
    else:
        response = {
            "type": "message",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": _draft_json()}],
        }
    transport = RecordingTransport(response)
    adapter = provider(model_name="synthetic-model", transport=transport)

    draft = generate_narrative_draft(
        adapter,
        build_anonymous_consultation_payload(_result()),
        "synthetic-secret-key",
    )

    assert draft.text.startswith("검증된 상담 결과")
    assert len(transport.calls) == 1
    url, headers, body, timeout = transport.calls[0]
    assert url == expected_url
    assert url.startswith("https://")
    assert "synthetic-secret-key" not in url
    assert headers[secret_header].endswith("synthetic-secret-key")
    assert "synthetic-secret-key" not in json.dumps(body, ensure_ascii=False)
    assert timeout <= 20
    serialized = json.dumps(body, ensure_ascii=False)
    assert "student_id" not in serialized
    assert "consultation_note" not in serialized
    assert "subject_name" not in serialized


def test_provider_specific_structured_output_contracts_are_sent() -> None:
    openai = RecordingTransport({"status": "completed", "output_text": _draft_json()})
    gemini = RecordingTransport({"candidates": [{"content": {"parts": [{"text": _draft_json()}]}}]})
    anthropic = RecordingTransport({"content": [{"type": "text", "text": _draft_json()}]})
    payload = build_anonymous_consultation_payload(_result())

    generate_narrative_draft(
        OpenAiNarrativeProvider("synthetic-model", transport=openai), payload, "key"
    )
    generate_narrative_draft(
        GeminiNarrativeProvider("synthetic-model", transport=gemini), payload, "key"
    )
    generate_narrative_draft(
        AnthropicNarrativeProvider("synthetic-model", transport=anthropic), payload, "key"
    )

    openai_body = openai.calls[0][2]
    assert openai_body["store"] is False
    assert openai_body["text"] == {
        "format": {
            "type": "json_schema",
            "name": "consultation_narrative_draft",
            "strict": True,
            "schema": openai_body["text"]["format"]["schema"],  # type: ignore[index]
        }
    }
    gemini_config = gemini.calls[0][2]["generationConfig"]
    assert gemini_config["responseMimeType"] == "application/json"  # type: ignore[index]
    assert "responseJsonSchema" in gemini_config  # type: ignore[operator]
    anthropic_format = anthropic.calls[0][2]["output_config"]
    assert anthropic_format["format"]["type"] == "json_schema"  # type: ignore[index]


@pytest.mark.parametrize("model_name", ["", "../model", "model?key=secret", "model name"])
def test_invalid_model_name_is_rejected_before_transport(model_name: str) -> None:
    transport = RecordingTransport({})

    with pytest.raises(NarrativeProviderError, match="모델"):
        OpenAiNarrativeProvider(model_name, transport=transport)

    assert transport.calls == []


@pytest.mark.parametrize(
    ("provider_code", "expected_type"),
    [
        ("OPENAI", OpenAiNarrativeProvider),
        ("GEMINI", GeminiNarrativeProvider),
        ("ANTHROPIC", AnthropicNarrativeProvider),
    ],
)
def test_provider_factory_returns_only_allowlisted_adapters(
    provider_code: str,
    expected_type: type[object],
) -> None:
    adapter = provider_adapter(provider_code, "synthetic-model", transport=RecordingTransport({}))

    assert isinstance(adapter, expected_type)
    with pytest.raises(NarrativeProviderError, match="공급자"):
        provider_adapter("UNKNOWN", "synthetic-model", transport=RecordingTransport({}))


@pytest.mark.parametrize(
    "response",
    [
        {},
        {"status": "incomplete", "output_text": _draft_json()},
        {"status": "completed", "output_text": "not-json"},
        {
            "status": "completed",
            "output_text": json.dumps({"draft_text": "문장", "check_items": [], "extra": "금지"}),
        },
    ],
)
def test_malformed_provider_output_is_rejected_without_echoing_body(
    response: dict[str, object],
) -> None:
    adapter = OpenAiNarrativeProvider("synthetic-model", transport=RecordingTransport(response))

    with pytest.raises(NarrativeProviderError) as caught:
        generate_narrative_draft(
            adapter,
            build_anonymous_consultation_payload(_result()),
            "synthetic-secret-key",
        )

    assert "synthetic-secret-key" not in str(caught.value)
    assert "extra" not in str(caught.value)


def test_transport_failure_is_exposed_as_sanitized_provider_error() -> None:
    class FailingTransport:
        def post_json(self, *args: object, **kwargs: object) -> dict[str, object]:
            raise ProviderHttpError("외부 공급자 요청이 실패했습니다.")

    adapter = OpenAiNarrativeProvider("synthetic-model", transport=FailingTransport())

    with pytest.raises(NarrativeProviderError, match="외부 공급자 요청이 실패했습니다"):
        generate_narrative_draft(
            adapter,
            build_anonymous_consultation_payload(_result()),
            "synthetic-secret-key",
        )


def test_http_transport_enforces_request_and_response_size_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = UrllibJsonTransport()
    with pytest.raises(ProviderHttpError, match="요청 크기 제한"):
        transport.post_json(
            "https://api.openai.com/v1/responses",
            headers={},
            payload={"value": "x" * MAX_REQUEST_BYTES},
            timeout_seconds=1,
        )

    class OversizedResponse:
        headers = Message()

        def __enter__(self) -> OversizedResponse:
            self.headers["Content-Type"] = "application/json"
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            assert size == MAX_RESPONSE_BYTES + 1
            return b"x" * size

    monkeypatch.setattr(
        "app.services.ai_http_providers.urlopen",
        lambda request, timeout: OversizedResponse(),
    )
    with pytest.raises(ProviderHttpError, match="응답 크기 제한"):
        transport.post_json(
            "https://api.openai.com/v1/responses",
            headers={},
            payload={"value": "safe"},
            timeout_seconds=1,
        )


def test_http_transport_does_not_retry_or_echo_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def fail_once(request: object, timeout: float) -> object:
        nonlocal calls
        calls += 1
        raise HTTPError(
            "https://api.openai.com/v1/responses",
            429,
            "provider-secret-body",
            Message(),
            None,
        )

    monkeypatch.setattr("app.services.ai_http_providers.urlopen", fail_once)

    with pytest.raises(ProviderHttpError, match=r"HTTP 429") as caught:
        UrllibJsonTransport().post_json(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": "Bearer synthetic-secret-key"},
            payload={"value": "safe"},
            timeout_seconds=1,
        )

    assert calls == 1
    assert "provider-secret-body" not in str(caught.value)
    assert "synthetic-secret-key" not in str(caught.value)
