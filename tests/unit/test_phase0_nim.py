"""Phase 0 NVIDIA NIM provider tests (issue #10).

Tests the NIM adapter's pure request-building, response-parsing, and cost
computation - deterministic, no network. The port methods are exercised
against a stubbed HTTP layer; the live end-to-end path is covered by the CLI
run (gated on NVIDIA_API_KEY), not by CI.
"""

import asyncio
from pathlib import Path

import pytest

from phase0.harness.models import Usage
from phase0.harness.providers.nim import (
    NimProvider,
    build_transcribe_request,
    compute_cost_inr,
    extract_confidence,
    parse_chat_content,
    parse_chat_usage,
    parse_transcribe_response,
)


def test_build_transcribe_request_uses_nim_model_and_hindi() -> None:
    request = build_transcribe_request(model="canary-1b-asr", language="hi-IN")
    assert request == {"model": "canary-1b-asr", "language": "hi-IN", "response_format": "json"}


def test_parse_transcribe_response_extracts_text() -> None:
    text = parse_transcribe_response({"text": "बुखार और खांसी"})
    assert text == "बुखार और खांसी"


def test_parse_transcribe_response_raises_on_no_text() -> None:
    with pytest.raises(RuntimeError, match="no transcript text"):
        parse_transcribe_response({})


def test_parse_chat_content_extracts_message() -> None:
    response = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"content": '{"chief_complaint": "बुखार"}'},
            }
        ]
    }
    assert parse_chat_content(response) == '{"chief_complaint": "बुखार"}'


def test_parse_chat_content_raises_on_empty_choices() -> None:
    with pytest.raises(RuntimeError, match="no choices"):
        parse_chat_content({"choices": []})


def test_parse_chat_content_raises_on_api_error() -> None:
    response = {"error": {"message": "Invalid API key provided"}}
    with pytest.raises(RuntimeError, match="API error"):
        parse_chat_content(response)


def test_parse_chat_content_raises_on_detail_payload_without_leaking_it() -> None:
    response = {"detail": "राम की बीमारी के बारे में गलत जानकारी"}
    with pytest.raises(RuntimeError, match="API error") as excinfo:
        parse_chat_content(response)
    assert "राम" not in str(excinfo.value)


def test_parse_chat_usage_extracts_token_counts() -> None:
    response = {"usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160}}
    usage = parse_chat_usage(
        response, provider="nim", model="meta/llama-3.1-8b-instruct", tier="prototyping"
    )
    assert usage.input_tokens == 120
    assert usage.output_tokens == 40
    assert usage.provider == "nim"
    assert usage.tier == "prototyping"


def test_parse_chat_usage_missing_counts_default_to_zero() -> None:
    usage = parse_chat_usage(
        {}, provider="nim", model="meta/llama-3.1-8b-instruct", tier="prototyping"
    )
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


def test_compute_cost_inr_uses_list_price() -> None:
    usage = Usage(
        provider="nim",
        model="meta/llama-3.1-8b-instruct",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cost_inr=0.0,
        latency_ms=0,
        tier="prototyping",
    )
    cost = compute_cost_inr(usage, price_per_1m_inr=100.0, price_per_1m_out_inr=300.0)
    assert cost == pytest.approx(400.0)


def test_compute_cost_inr_zero_at_preview_list_price() -> None:
    # The hosted NIM preview is free; production requires NVIDIA AI Enterprise
    # (recorded as the licensing caveat), so the list price is zero.
    usage = Usage(
        provider="nim",
        model="meta/llama-3.1-8b-instruct",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cost_inr=0.0,
        latency_ms=0,
        tier="prototyping",
    )
    cost = compute_cost_inr(usage, price_per_1m_inr=0.0, price_per_1m_out_inr=0.0)
    assert cost == pytest.approx(0.0)


# --- structuring confidence (issue #10, same AMB-006 path as Gemini) ---------


def test_extract_confidence_reads_self_report() -> None:
    assert extract_confidence({"structuring_confidence": 0.82}) == pytest.approx(0.82)


def test_extract_confidence_clamps_into_range() -> None:
    assert extract_confidence({"structuring_confidence": 1.5}) == pytest.approx(1.0)
    assert extract_confidence({"structuring_confidence": -0.2}) == pytest.approx(0.0)


def test_extract_confidence_missing_or_invalid_is_none() -> None:
    assert extract_confidence({}) is None
    assert extract_confidence({"structuring_confidence": "oops"}) is None


# --- Gateway port shape + per-call Usage (issue #10, AC-1 / AC-5) -------------


def _provider(monkeypatch: pytest.MonkeyPatch) -> NimProvider:
    monkeypatch.setattr("phase0.harness.providers.nim._load_api_key", lambda explicit: "test-key")
    return NimProvider()


def test_provider_implements_the_gateway_port(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch)
    assert provider.name == "nim"
    assert asyncio.iscoroutinefunction(provider.transcribe)
    assert asyncio.iscoroutinefunction(provider.structure)
    assert provider.tier == "prototyping"


class _RecordingClient:
    """Fake httpx client that records the URLs it is asked to POST to."""

    def __init__(self) -> None:
        self.urls: list[str] = []

    async def post(self, url: str, **kwargs: object) -> dict[str, object]:
        self.urls.append(url)
        if url.endswith("audio/transcriptions"):
            return {"text": "बुखार और खांसी", "_latency_ms": 1}
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": '{"chief_complaint": "बुखार", "structuring_confidence": 0.9}'
                    },
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "_latency_ms": 1,
        }


async def _capture_urls(
    monkeypatch: pytest.MonkeyPatch, provider: NimProvider, client: _RecordingClient
) -> None:
    async def run_send(send: object) -> dict[str, object]:
        return await send(client)  # type: ignore[operator]

    monkeypatch.setattr(provider, "_post", run_send)


async def test_transcribe_targets_base_url_plus_asr_endpoint(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _provider(monkeypatch)
    client = _RecordingClient()
    await _capture_urls(monkeypatch, provider, client)
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    await provider.transcribe(audio, "sample_0001")
    assert client.urls == ["https://integrate.api.nvidia.com/v1/audio/transcriptions"]


async def test_structure_targets_base_url_plus_chat_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(monkeypatch)
    client = _RecordingClient()
    await _capture_urls(monkeypatch, provider, client)
    await provider.structure("बुखार और खांसी", "sample_0001")
    assert client.urls == ["https://integrate.api.nvidia.com/v1/chat/completions"]


async def test_transcribe_records_asr_usage_without_token_counts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _provider(monkeypatch)

    async def fake_post(send: object) -> dict[str, object]:
        return {"text": "बुखार और खांसी", "_latency_ms": 12}

    monkeypatch.setattr(provider, "_post", fake_post)
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    result = await provider.transcribe(audio, "sample_0001")
    assert result.text == "बुखार और खांसी"
    assert result.usage.provider == "nim"
    assert result.usage.model == "canary-1b-asr"
    assert result.usage.tier == "prototyping"
    # The ASR API does not report token counts, so they are recorded as 0
    # (honest, not estimated); the preview tier is free, so cost is 0.
    assert result.usage.input_tokens == 0
    assert result.usage.output_tokens == 0
    assert result.usage.cost_inr == pytest.approx(0.0)
    assert result.usage.latency_ms == 12


async def test_structure_records_chat_usage_and_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(monkeypatch)

    async def fake_post(send: object) -> dict[str, object]:
        return {
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "content": '{"chief_complaint": "बुखार", "structuring_confidence": 0.9}'
                    },
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "_latency_ms": 7,
        }

    monkeypatch.setattr(provider, "_post", fake_post)
    result = await provider.structure("बुखार और खांसी", "sample_0001")
    assert result.structured["chief_complaint"] == "बुखार"
    assert result.confidence == pytest.approx(0.9)
    assert result.usage.provider == "nim"
    assert result.usage.model == "meta/llama-3.1-8b-instruct"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5
    assert result.usage.cost_inr == pytest.approx(0.0)
    assert result.usage.latency_ms == 7


class _StubHttpResponse:
    """Minimal httpx.Response stand-in for exercising the ``_post`` retry loop."""

    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def json(self) -> dict[str, object]:
        return {}


async def test_post_withholds_error_response_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _provider(monkeypatch)
    provider.max_retries = 1
    provider.retry_backoff_seconds = 0.0
    provider.quota_backoff_seconds = 0.0

    async def fake_send(client: object) -> _StubHttpResponse:
        # A provider error body derived from the transcript may carry PHI
        # (error-handling-observability §2); it must never reach the exception.
        return _StubHttpResponse(500, '{"error": {"message": "राम की बीमारी"}}')

    with pytest.raises(RuntimeError, match="HTTP 500") as excinfo:
        await provider._post(fake_send)  # type: ignore[arg-type]
    assert "राम" not in str(excinfo.value)
