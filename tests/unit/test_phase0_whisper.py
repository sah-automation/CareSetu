"""Phase 0 Whisper provider tests (issue #9).

Tests the OpenAI Whisper adapter's pure request-building, response-parsing, and
cost computation — deterministic, no network. The port methods are exercised
against a stubbed HTTP layer; the live end-to-end path is covered by the CLI
run (gated on OPENAI_API_KEY), not by CI.
"""

import asyncio
from pathlib import Path

import pytest

from phase0.harness.models import Usage
from phase0.harness.providers.whisper import (
    WhisperProvider,
    build_transcribe_request,
    compute_cost_inr,
    compute_transcription_cost_inr,
    extract_confidence,
    parse_chat_content,
    parse_chat_usage,
    parse_transcribe_response,
)


def test_build_transcribe_request_uses_whisper_model_and_hindi() -> None:
    request = build_transcribe_request(model="whisper-1", language="hi")
    # verbose_json (not plain json) so the per-second cost model gets duration.
    assert request == {
        "model": "whisper-1",
        "language": "hi",
        "response_format": "verbose_json",
    }


def test_parse_transcribe_response_extracts_text_and_duration() -> None:
    text, duration = parse_transcribe_response({"text": "बुखार और खांसी", "duration": 12.5})
    assert text == "बुखार और खांसी"
    assert duration == pytest.approx(12.5)


def test_parse_transcribe_response_missing_duration_defaults_zero() -> None:
    text, duration = parse_transcribe_response({"text": "ठीक है"})
    assert text == "ठीक है"
    assert duration == 0.0


def test_parse_transcribe_response_raises_on_no_text() -> None:
    with pytest.raises(RuntimeError, match="no transcript text"):
        parse_transcribe_response({"duration": 3.0})


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
    with pytest.raises(RuntimeError, match="Invalid API key"):
        parse_chat_content(response)


def test_parse_chat_usage_extracts_token_counts() -> None:
    response = {"usage": {"prompt_tokens": 120, "completion_tokens": 40, "total_tokens": 160}}
    usage = parse_chat_usage(response, provider="whisper", model="gpt-4o-mini", tier="paid")
    assert usage.input_tokens == 120
    assert usage.output_tokens == 40
    assert usage.provider == "whisper"
    assert usage.tier == "paid"


def test_parse_chat_usage_missing_counts_default_to_zero() -> None:
    usage = parse_chat_usage({}, provider="whisper", model="gpt-4o-mini", tier="paid")
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


def test_compute_transcription_cost_inr_uses_per_second_price() -> None:
    cost = compute_transcription_cost_inr(duration_seconds=60.0, price_inr_per_second=0.0083)
    assert cost == pytest.approx(0.498)


def test_compute_transcription_cost_inr_zero_for_no_audio() -> None:
    cost = compute_transcription_cost_inr(duration_seconds=0.0, price_inr_per_second=0.0083)
    assert cost == pytest.approx(0.0)


def test_compute_cost_inr_uses_list_price() -> None:
    usage = Usage(
        provider="whisper",
        model="gpt-4o-mini",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cost_inr=0.0,
        latency_ms=0,
        tier="paid",
    )
    cost = compute_cost_inr(usage, price_per_1m_inr=100.0, price_per_1m_out_inr=300.0)
    assert cost == pytest.approx(400.0)


def test_compute_cost_inr_zero_for_no_tokens() -> None:
    usage = Usage(
        provider="whisper",
        model="gpt-4o-mini",
        input_tokens=0,
        output_tokens=0,
        cost_inr=0.0,
        latency_ms=0,
        tier="paid",
    )
    cost = compute_cost_inr(usage, price_per_1m_inr=100.0, price_per_1m_out_inr=300.0)
    assert cost == pytest.approx(0.0)


# --- structuring confidence (issue #9, same AMB-006 path as Gemini) -----------


def test_extract_confidence_reads_self_report() -> None:
    assert extract_confidence({"structuring_confidence": 0.82}) == pytest.approx(0.82)


def test_extract_confidence_clamps_into_range() -> None:
    assert extract_confidence({"structuring_confidence": 1.5}) == pytest.approx(1.0)
    assert extract_confidence({"structuring_confidence": -0.2}) == pytest.approx(0.0)


def test_extract_confidence_missing_or_invalid_is_none() -> None:
    assert extract_confidence({}) is None
    assert extract_confidence({"structuring_confidence": "oops"}) is None


# --- Gateway port shape + per-call Usage (issue #9, AC-1 / AC-5) --------------


def _provider(monkeypatch: pytest.MonkeyPatch) -> WhisperProvider:
    monkeypatch.setattr(
        "phase0.harness.providers.whisper._load_api_key", lambda explicit: "test-key"
    )
    return WhisperProvider()


def test_provider_implements_the_gateway_port(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider(monkeypatch)
    assert provider.name == "whisper"
    assert asyncio.iscoroutinefunction(provider.transcribe)
    assert asyncio.iscoroutinefunction(provider.structure)
    assert provider.tier == "paid"


async def test_transcribe_records_asr_usage_from_duration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    provider = _provider(monkeypatch)

    async def fake_post(send: object) -> dict[str, object]:
        return {"text": "बुखार और खांसी", "duration": 3.0, "_latency_ms": 12}

    monkeypatch.setattr(provider, "_post", fake_post)
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFF")
    result = await provider.transcribe(audio, "sample_0001")
    assert result.text == "बुखार और खांसी"
    assert result.usage.provider == "whisper"
    assert result.usage.model == "whisper-1"
    assert result.usage.tier == "paid"
    assert result.usage.input_tokens == 0
    assert result.usage.cost_inr == pytest.approx(3.0 * 0.0001 * 83.0)
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
    assert result.usage.provider == "whisper"
    assert result.usage.model == "gpt-4o-mini"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 5
    assert result.usage.cost_inr > 0
    assert result.usage.latency_ms == 7
