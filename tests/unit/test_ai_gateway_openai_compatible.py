"""PHASE-7 T02 (#379): OpenAI-compatible adapter unit tests.

Acceptance contract from the ticket: happy-path parse, token extraction,
429/5xx retry then outage, 4xx non-retryable, malformed payload non-retryable,
egress payload carries only intake context (never name/phone).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from modules.intake.adapters.ai_gateway import (
    AiEgressContext,
    AiGateway,
    DraftRxRequest,
    StructureRequest,
    StructureResult,
    TranscribeRequest,
)
from modules.intake.adapters.ai_provider_ext import Ext002CallError
from modules.intake.adapters.ai_provider_openai_compatible import (
    OpenAiCompatibleAdapter,
    build_openai_compatible_gateway,
)


def _context() -> AiEgressContext:
    return AiEgressContext(language="hi", age_range="30-40", sex="male")


def _structure_request() -> StructureRequest:
    return StructureRequest(
        transcript="mujhe bukhar hai",
        source="voice",
        context=_context(),
    )


def _mock_structure_response(
    *,
    chief_complaints: list[str] | None = None,
    symptoms: list[str] | None = None,
    duration: str = "1 week",
    confidence: float = 0.8,
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
) -> dict[str, Any]:
    content = json.dumps(
        {
            "chief_complaints": chief_complaints or ["fever"],
            "symptoms": symptoms or ["high temperature"],
            "duration": duration,
            "confidence": confidence,
        }
    )
    response: dict[str, Any] = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
        },
    }
    return response


def _error_response(status_code: int, body: str = '{"error": "bad"}') -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=body.encode(),
        request=httpx.Request("POST", "https://ext.example/chat/completions"),
    )


def _success_response(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        status_code=200,
        json=payload,
        request=httpx.Request("POST", "https://ext.example/chat/completions"),
    )


def _network_error_request() -> httpx.Response:
    raise httpx.ConnectError("connection refused")


def _make_adapter(
    transport: httpx.AsyncBaseTransport,
    *,
    max_retries: int = 3,
) -> OpenAiCompatibleAdapter:
    client = httpx.AsyncClient(transport=transport, timeout=5.0)
    return OpenAiCompatibleAdapter(
        api_key="test-key",
        base_url="https://ext.example",
        model="test-model",
        timeout_seconds=5.0,
        max_retries=max_retries,
        client=client,
        sleep=_noop_sleep,
    )


async def _noop_sleep(_: float) -> None:
    pass


# --- Happy path ---


async def test_structure_happy_path_parse() -> None:
    mock_resp = _mock_structure_response()
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    result = await adapter.structure(_structure_request())

    assert isinstance(result, StructureResult)
    assert result.chief_complaints == ["fever"]
    assert result.symptoms == ["high temperature"]
    assert result.duration == "1 week"
    assert result.confidence == 0.8


async def test_structure_custom_fields() -> None:
    mock_resp = _mock_structure_response(
        chief_complaints=["cough", "cold"],
        symptoms=["runny nose", "sore throat"],
        duration="3 days",
        confidence=0.65,
    )
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    result = await adapter.structure(_structure_request())

    assert result.chief_complaints == ["cough", "cold"]
    assert result.symptoms == ["runny nose", "sore throat"]
    assert result.duration == "3 days"
    assert result.confidence == 0.65


# --- Token extraction ---


async def test_structure_usage_tokens_extracted() -> None:
    mock_resp = _mock_structure_response(prompt_tokens=150, completion_tokens=75)
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    result = await adapter.structure(_structure_request())

    assert isinstance(result, StructureResult)


async def test_structure_usage_tokens_missing() -> None:
    mock_resp: dict[str, Any] = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "chief_complaints": ["fever"],
                            "symptoms": ["high temperature"],
                            "duration": "1 week",
                            "confidence": 0.8,
                        }
                    ),
                },
                "finish_reason": "stop",
            }
        ],
    }
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    result = await adapter.structure(_structure_request())

    assert isinstance(result, StructureResult)


# --- 429 / 5xx retry then outage ---


async def test_structure_429_retry_then_outage() -> None:
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _error_response(429)

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport, max_retries=2)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.structure(_structure_request())

    assert exc_info.value.retries_exhausted is True
    assert call_count == 3  # initial + 2 retries


async def test_structure_500_retry_then_outage() -> None:
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _error_response(500)

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport, max_retries=2)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.structure(_structure_request())

    assert exc_info.value.retries_exhausted is True
    assert call_count == 3


# --- 4xx non-retryable ---


async def test_structure_400_non_retryable() -> None:
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _error_response(400, '{"error": "bad request"}')

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport, max_retries=2)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.structure(_structure_request())

    assert exc_info.value.retries_exhausted is False
    assert call_count == 1  # no retries


async def test_structure_403_non_retryable() -> None:
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _error_response(403)

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport, max_retries=2)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.structure(_structure_request())

    assert exc_info.value.retries_exhausted is False
    assert call_count == 1


# --- Malformed payload non-retryable ---


async def test_structure_non_json_response_non_retryable() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status_code=200,
            content=b"not json at all",
            request=httpx.Request("POST", "https://ext.example/chat/completions"),
        )
    )
    adapter = _make_adapter(transport)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.structure(_structure_request())

    assert exc_info.value.retries_exhausted is False


async def test_structure_wrong_json_shape_non_retryable() -> None:
    transport = httpx.MockTransport(
        lambda request: _success_response({"not": "the right shape"})
    )
    adapter = _make_adapter(transport)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.structure(_structure_request())

    assert exc_info.value.retries_exhausted is False


async def test_structure_content_not_json_non_retryable() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "this is not valid json",
                },
                "finish_reason": "stop",
            }
        ],
    }
    transport = httpx.MockTransport(lambda request: _success_response(payload))
    adapter = _make_adapter(transport)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.structure(_structure_request())

    assert exc_info.value.retries_exhausted is False


async def test_structure_content_wrong_schema_non_retryable() -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"wrong": "schema"}),
                },
                "finish_reason": "stop",
            }
        ],
    }
    transport = httpx.MockTransport(lambda request: _success_response(payload))
    adapter = _make_adapter(transport)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.structure(_structure_request())

    assert exc_info.value.retries_exhausted is False


# --- Network error ---


async def test_structure_network_error_retry_then_outage() -> None:
    transport = httpx.MockTransport(lambda request: _network_error_request())
    adapter = _make_adapter(transport, max_retries=2)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.structure(_structure_request())

    assert exc_info.value.retries_exhausted is True


# --- Egress payload carries only intake context ---


async def test_egress_payload_carries_only_intake_context() -> None:
    captured_requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return _success_response(_mock_structure_response())

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport)

    await adapter.structure(_structure_request())

    assert len(captured_requests) == 1
    body = json.loads(captured_requests[0].content)
    messages = body["messages"]
    user_message = messages[1]["content"]
    assert "mujhe bukhar hai" in user_message
    assert "hi" in user_message
    assert "30-40" in user_message
    assert "male" in user_message
    assert "name" not in user_message
    assert "phone" not in user_message


async def test_egress_no_patient_identifiers_in_payload() -> None:
    captured_requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return _success_response(_mock_structure_response())

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport)

    await adapter.structure(_structure_request())

    body = json.loads(captured_requests[0].content)
    assert "name" not in body
    assert "phone" not in body
    assert "patient_id" not in body


# --- transcribe / draft_rx raise non-retryable error ---


async def test_transcribe_raises_not_supported() -> None:
    adapter = _make_adapter(
        httpx.MockTransport(lambda request: _success_response({}))
    )

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.transcribe(
            TranscribeRequest(audio_ref="media/abc", mode="voice", context=_context())
        )

    assert exc_info.value.retries_exhausted is False
    assert "not supported" in str(exc_info.value)


async def test_draft_rx_raises_not_supported() -> None:
    adapter = _make_adapter(
        httpx.MockTransport(lambda request: _success_response({}))
    )

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.draft_rx(
            DraftRxRequest(
                doctor_input_ref="voice_note/1",
                pre_summary_ref="pre_summary/2",
                patient_history_summary="mock history",
                context=_context(),
            )
        )

    assert exc_info.value.retries_exhausted is False
    assert "not supported" in str(exc_info.value)


# --- Protocol conformance ---


async def test_adapter_implements_all_three_operations() -> None:
    adapter = OpenAiCompatibleAdapter(
        api_key="k",
        base_url="https://ext.example",
        model="test-model",
    )

    assert callable(adapter.transcribe)
    assert callable(adapter.structure)
    assert callable(adapter.draft_rx)


async def test_adapter_typed_as_port() -> None:
    transport = httpx.MockTransport(
        lambda request: _success_response(_mock_structure_response())
    )
    client = httpx.AsyncClient(transport=transport, timeout=5.0)
    gateway: AiGateway = OpenAiCompatibleAdapter(
        api_key="k",
        base_url="https://ext.example",
        model="test-model",
        client=client,
        sleep=_noop_sleep,
    )

    result = await gateway.structure(
        StructureRequest(transcript="x", source="text", context=_context())
    )
    assert isinstance(result, StructureResult)


# --- Builder function ---


async def test_build_openai_compatible_gateway_returns_adapter() -> None:
    transport = httpx.MockTransport(
        lambda request: _success_response(_mock_structure_response())
    )
    client = httpx.AsyncClient(transport=transport, timeout=5.0)
    gateway: AiGateway = build_openai_compatible_gateway(
        api_key="k",
        base_url="https://ext.example",
        model="test-model",
        client=client,
        sleep=_noop_sleep,
    )

    result = await gateway.structure(
        StructureRequest(transcript="x", source="text", context=_context())
    )
    assert isinstance(result, StructureResult)


# --- Bearer auth ---


async def test_structure_sends_bearer_auth() -> None:
    captured_requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return _success_response(_mock_structure_response())

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport)

    await adapter.structure(_structure_request())

    assert len(captured_requests) == 1
    auth_header = captured_requests[0].headers.get("authorization")
    assert auth_header == "Bearer test-key"


# --- JSON-mode response format ---


async def test_structure_requests_json_mode() -> None:
    captured_requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return _success_response(_mock_structure_response())

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport)

    await adapter.structure(_structure_request())

    body = json.loads(captured_requests[0].content)
    assert body["response_format"] == {"type": "json_object"}


# --- Model in payload ---


async def test_structure_sends_model() -> None:
    captured_requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return _success_response(_mock_structure_response())

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport)

    await adapter.structure(_structure_request())

    body = json.loads(captured_requests[0].content)
    assert body["model"] == "test-model"
