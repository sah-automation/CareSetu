"""OpenAI-compatible adapter unit tests (#379 structure leg, #387 ASR leg).

Structure-leg acceptance contract (#379): happy-path parse, token extraction,
429/5xx retry then outage, 4xx non-retryable, malformed payload non-retryable,
egress payload carries only intake context (never name/phone).

Transcribe-leg acceptance contract (#387/#392): happy-path parse into
``TranscribeResult``, transcription confidence proxy and per-segment
confidence, usage extraction when present (top-level and vendor extension),
429/5xx retry-then-outage, 4xx/malformed non-retryable, multipart egress
carries the decrypted clip + model + declared language (never audio_ref /
name / phone / full context), and a request with no clip bytes fails closed as
a contract rejection.
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
    TranscribeResult,
)
from modules.intake.adapters.ai_provider_ext import Ext002CallError
from modules.intake.adapters.ai_provider_openai_compatible import (
    OpenAiCompatibleAdapter,
    build_openai_compatible_gateway,
)


def _context() -> AiEgressContext:
    return AiEgressContext(language="hi")


def _structure_request() -> StructureRequest:
    return StructureRequest(
        transcript="mujhe bukhar hai",
        source="voice",
        context=_context(),
    )


_AUDIO_BYTES = b"fake-pcm-audio-bytes"


def _transcribe_request() -> TranscribeRequest:
    return TranscribeRequest(
        audio_ref="media/abc.mp3",
        audio_bytes=_AUDIO_BYTES,
        mode="voice",
        context=_context(),
    )


def _parse_multipart(request: httpx.Request) -> dict[str, bytes]:
    """Parse a multipart/form-data request body into {field: bytes}."""
    content_type = request.headers.get("content-type", "")
    assert content_type.startswith("multipart/form-data"), content_type
    boundary = content_type.split("boundary=", 1)[1].strip().strip('"').encode()
    parts: dict[str, bytes] = {}
    for chunk in request.content.split(b"--" + boundary):
        if not chunk or chunk == b"--":
            continue
        if b"\r\n\r\n" not in chunk:
            continue
        head, value = chunk.split(b"\r\n\r\n", 1)
        name: str | None = None
        for line in head.split(b"\r\n"):
            if not line.lower().startswith(b"content-disposition"):
                continue
            for param in line.decode(errors="ignore").split(";"):
                param = param.strip()
                if param.startswith("name="):
                    name = param.split("=", 1)[1].strip('"')
        if name is not None:
            parts[name] = value.removesuffix(b"\r\n")
    return parts


def _mock_transcription_response(
    *,
    text: str = "mujhe bukhar hai",
    language: str | None = None,
    segments: list[dict[str, Any]] | None = None,
    usage: dict[str, Any] | None = None,
    vendor_usage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {"text": text}
    if language is not None:
        response["language"] = language
    if segments is not None:
        response["segments"] = segments
    if usage is not None:
        response["usage"] = usage
    if vendor_usage is not None:
        response["x_groq"] = {"usage": vendor_usage}
    return response


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
    assert result.input_tokens == 150
    assert result.output_tokens == 75


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
    assert result.input_tokens == 0
    assert result.output_tokens == 0


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
    transport = httpx.MockTransport(lambda request: _success_response({"not": "the right shape"}))
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
    assert "Language: hi" in user_message
    for forbidden in ("Age range", "Sex", "name", "phone"):
        assert forbidden not in user_message, f"prompt carried forbidden term {forbidden!r}"


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


def test_built_structure_prompt_admits_only_language_and_transcript() -> None:
    """Guardrail (PS-02): the built prompt admits exactly language + transcript.

    The user message is the composed prompt that actually reaches the provider;
    pinning its shape prevents age/sex/identity from re-entering the egress
    boundary through the prompt leg.
    """
    adapter = _make_adapter(httpx.MockTransport(lambda request: _success_response({})))
    messages = adapter._build_messages("mujhe bukhar hai", _context())

    assert messages[0]["role"] == "system"
    user_message = messages[1]
    assert user_message["role"] == "user"
    assert user_message["content"] == "Transcript: mujhe bukhar hai\nLanguage: hi"


# --- transcribe: happy path ---


async def test_transcribe_happy_path_parse() -> None:
    mock_resp = _mock_transcription_response()
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    result = await adapter.transcribe(_transcribe_request())

    assert isinstance(result, TranscribeResult)
    assert result.transcript == "mujhe bukhar hai"
    assert result.language == "hi"


async def test_transcribe_strips_transcript_whitespace() -> None:
    mock_resp = _mock_transcription_response(text="  mujhe bukhar hai  ")
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    result = await adapter.transcribe(_transcribe_request())

    assert result.transcript == "mujhe bukhar hai"


# --- transcribe: confidence proxy ---


async def test_transcribe_confidence_proxy_defaults_when_absent() -> None:
    mock_resp = _mock_transcription_response()
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    result = await adapter.transcribe(_transcribe_request())

    assert result.confidence == pytest.approx(0.8)


async def test_transcribe_confidence_proxy_averages_segment_confidence() -> None:
    mock_resp = _mock_transcription_response(
        segments=[
            {"id": 0, "confidence": 0.9},
            {"id": 1, "confidence": 0.7},
            {"id": 2, "confidence": 0.8},
        ]
    )
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    result = await adapter.transcribe(_transcribe_request())

    assert result.confidence == pytest.approx(0.8)


async def test_transcribe_confidence_proxy_ignores_non_confidence_segments() -> None:
    mock_resp = _mock_transcription_response(
        segments=[{"id": 0, "no_speech_prob": 0.1}, {"id": 1, "confidence": 0.6}]
    )
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    result = await adapter.transcribe(_transcribe_request())

    assert result.confidence == pytest.approx(0.6)


# --- transcribe: language handling ---


async def test_transcribe_language_defaults_to_context_language() -> None:
    mock_resp = _mock_transcription_response()
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    result = await adapter.transcribe(_transcribe_request())

    assert result.language == "hi"


async def test_transcribe_uses_provider_language_when_present() -> None:
    mock_resp = _mock_transcription_response(language="en")
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    result = await adapter.transcribe(_transcribe_request())

    assert result.language == "en"


async def test_transcribe_unexpected_language_non_retryable() -> None:
    mock_resp = _mock_transcription_response(language="english")
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.transcribe(_transcribe_request())

    assert exc_info.value.retries_exhausted is False


# --- transcribe: usage extraction ---


async def test_transcribe_usage_extracted_when_present() -> None:
    mock_resp = _mock_transcription_response(usage={"prompt_tokens": 10, "completion_tokens": 5})
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    result = await adapter.transcribe(_transcribe_request())

    assert isinstance(result, TranscribeResult)
    assert result.input_tokens == 10
    assert result.output_tokens == 5


async def test_transcribe_usage_extracted_from_vendor_extension() -> None:
    mock_resp = _mock_transcription_response(
        vendor_usage={"prompt_tokens": 7, "completion_tokens": 3}
    )
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    result = await adapter.transcribe(_transcribe_request())

    assert isinstance(result, TranscribeResult)
    assert result.input_tokens == 7
    assert result.output_tokens == 3


async def test_transcribe_usage_zero_when_absent() -> None:
    transport = httpx.MockTransport(
        lambda request: _success_response(_mock_transcription_response())
    )
    adapter = _make_adapter(transport)

    result = await adapter.transcribe(_transcribe_request())

    assert isinstance(result, TranscribeResult)
    assert result.input_tokens == 0
    assert result.output_tokens == 0


# --- transcribe: 429 / 5xx retry then outage ---


async def test_transcribe_429_retry_then_outage() -> None:
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _error_response(429)

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport, max_retries=2)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.transcribe(_transcribe_request())

    assert exc_info.value.retries_exhausted is True
    assert call_count == 3  # initial + 2 retries


async def test_transcribe_500_retry_then_outage() -> None:
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _error_response(500)

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport, max_retries=2)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.transcribe(_transcribe_request())

    assert exc_info.value.retries_exhausted is True
    assert call_count == 3


# --- transcribe: 4xx non-retryable ---


async def test_transcribe_400_non_retryable() -> None:
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _error_response(400, '{"error": "bad request"}')

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport, max_retries=2)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.transcribe(_transcribe_request())

    assert exc_info.value.retries_exhausted is False
    assert call_count == 1  # no retries


async def test_transcribe_403_non_retryable() -> None:
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return _error_response(403)

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport, max_retries=2)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.transcribe(_transcribe_request())

    assert exc_info.value.retries_exhausted is False
    assert call_count == 1


# --- transcribe: malformed payload non-retryable ---


async def test_transcribe_non_json_response_non_retryable() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status_code=200,
            content=b"not json at all",
            request=httpx.Request("POST", "https://ext.example/audio/transcriptions"),
        )
    )
    adapter = _make_adapter(transport)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.transcribe(_transcribe_request())

    assert exc_info.value.retries_exhausted is False


async def test_transcribe_wrong_json_shape_non_retryable() -> None:
    transport = httpx.MockTransport(
        lambda request: _success_response(
            {"not": "the right shape"},
        )
    )
    adapter = _make_adapter(transport)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.transcribe(_transcribe_request())

    assert exc_info.value.retries_exhausted is False


async def test_transcribe_missing_text_non_retryable() -> None:
    mock_resp = _mock_transcription_response(text="")
    transport = httpx.MockTransport(lambda request: _success_response(mock_resp))
    adapter = _make_adapter(transport)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.transcribe(_transcribe_request())

    assert exc_info.value.retries_exhausted is False


# --- transcribe: network error ---


async def test_transcribe_network_error_retry_then_outage() -> None:
    transport = httpx.MockTransport(lambda request: _network_error_request())
    adapter = _make_adapter(transport, max_retries=2)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.transcribe(_transcribe_request())

    assert exc_info.value.retries_exhausted is True


# --- transcribe: egress only carries reference + intake context ---


async def test_transcribe_posts_multipart_form_data() -> None:
    captured_requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return _success_response(_mock_transcription_response())

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport)

    await adapter.transcribe(_transcribe_request())

    assert len(captured_requests) == 1
    assert captured_requests[0].url.path == "/audio/transcriptions"
    assert captured_requests[0].headers.get("authorization") == "Bearer test-key"
    parts = _parse_multipart(captured_requests[0])
    assert parts["model"] == b"whisper-large-v3-turbo"
    assert parts["language"] == b"hi"
    assert parts["file"] == _AUDIO_BYTES
    assert b"Content-Type: audio/mpeg" in captured_requests[0].content


async def test_transcribe_multipart_mime_matches_clip_extension() -> None:
    captured_requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return _success_response(_mock_transcription_response())

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport)

    await adapter.transcribe(
        TranscribeRequest(
            audio_ref="media/record.wav",
            audio_bytes=_AUDIO_BYTES,
            mode="voice",
            context=_context(),
        )
    )

    body = captured_requests[0].content
    assert b"Content-Type: audio/wav" in body
    assert b'filename="record.wav"' in body
    assert b"audio/mpeg" not in body


async def test_transcribe_asr_model_overridable() -> None:
    captured_requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return _success_response(_mock_transcription_response())

    transport = httpx.MockTransport(_handler)
    client = httpx.AsyncClient(transport=transport, timeout=5.0)
    adapter = OpenAiCompatibleAdapter(
        api_key="test-key",
        base_url="https://ext.example",
        model="test-model",
        asr_model="whisper-large-v3",
        client=client,
        sleep=_noop_sleep,
    )

    await adapter.transcribe(_transcribe_request())

    parts = _parse_multipart(captured_requests[0])
    assert parts["model"] == b"whisper-large-v3"
    assert adapter.effective_model == "test-model"


async def test_transcribe_egress_carries_only_clip_and_context() -> None:
    captured_requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return _success_response(_mock_transcription_response())

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport)

    await adapter.transcribe(_transcribe_request())

    parts = _parse_multipart(captured_requests[0])
    assert parts["file"] == _AUDIO_BYTES
    assert parts["model"] == b"whisper-large-v3-turbo"
    assert parts["language"] == b"hi"
    assert set(parts) == {"file", "model", "language"}
    for forbidden in ("name", "phone", "patient_id"):
        assert forbidden not in parts, f"egress carried forbidden field {forbidden!r}"


async def test_transcribe_no_bytes_fails_closed() -> None:
    captured_requests: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return _success_response(_mock_transcription_response())

    transport = httpx.MockTransport(_handler)
    adapter = _make_adapter(transport)

    with pytest.raises(Ext002CallError) as exc_info:
        await adapter.transcribe(
            TranscribeRequest(
                audio_ref="media/abc.mp3",
                mode="voice",
                context=_context(),
            )
        )

    assert exc_info.value.retries_exhausted is False
    assert "no bytes" in str(exc_info.value)
    assert captured_requests == []  # fails closed before any HTTP call


# --- draft_rx raises non-retryable error ---


async def test_draft_rx_raises_not_supported() -> None:
    adapter = _make_adapter(httpx.MockTransport(lambda request: _success_response({})))

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
    transport = httpx.MockTransport(lambda request: _success_response(_mock_structure_response()))
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
    transport = httpx.MockTransport(lambda request: _success_response(_mock_structure_response()))
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
