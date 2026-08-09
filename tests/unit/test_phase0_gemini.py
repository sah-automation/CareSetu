"""Phase 0 Gemini provider tests (issue #4).

Tests the Gemini adapter's pure request-building, response-parsing, and cost
computation — deterministic, no network. The live end-to-end path is covered
by the CLI run (gated on GEMINI_API_KEY), not by CI.
"""

import pytest

from phase0.harness.models import Usage
from phase0.harness.providers.gemini import (
    build_transcribe_request,
    compute_cost_inr,
    extract_confidence,
    parse_generate_response,
    parse_usage,
)


def test_build_transcribe_request_embeds_audio_and_prompt() -> None:
    request = build_transcribe_request(
        model="gemini-2.5-flash", audio_bytes=b"RIFF\x24\x00", mime="audio/wav"
    )
    assert request["contents"][0]["role"] == "user"
    parts = request["contents"][0]["parts"]
    assert parts[1]["inline_data"] == {"mime_type": "audio/wav", "data": "UklGRiQA"}


def test_build_transcribe_request_has_low_temperature() -> None:
    request = build_transcribe_request(model="gemini-2.5-flash", audio_bytes=b"x", mime="audio/wav")
    assert request["generationConfig"]["temperature"] == 0.0


def test_parse_usage_extracts_token_counts() -> None:
    response = {
        "usageMetadata": {
            "promptTokenCount": 120,
            "candidatesTokenCount": 40,
            "totalTokenCount": 160,
        }
    }
    usage = parse_usage(response, provider="gemini", model="gemini-2.5-flash", tier="free")
    assert usage.input_tokens == 120
    assert usage.output_tokens == 40
    assert usage.provider == "gemini"
    assert usage.tier == "free"


def test_parse_usage_missing_counts_default_to_zero() -> None:
    usage = parse_usage({}, provider="gemini", model="gemini-2.5-flash", tier="free")
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0


def test_parse_generate_response_extracts_text() -> None:
    response = {"candidates": [{"content": {"parts": [{"text": "बुखार और खांसी"}]}}]}
    assert parse_generate_response(response) == "बुखार और खांसी"


def test_parse_generate_response_raises_on_empty_candidates() -> None:
    with pytest.raises(RuntimeError, match="no candidates"):
        parse_generate_response({"candidates": []})


def test_parse_generate_response_raises_on_blocked_content() -> None:
    response = {"candidates": [{"finishReason": "SAFETY", "content": {"parts": []}}]}
    with pytest.raises(RuntimeError, match="SAFETY"):
        parse_generate_response(response)


def test_compute_cost_inr_uses_list_price() -> None:
    usage = Usage(
        provider="gemini",
        model="gemini-2.5-flash",
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
        provider="gemini",
        model="gemini-2.5-flash",
        input_tokens=0,
        output_tokens=0,
        cost_inr=0.0,
        latency_ms=0,
        tier="free",
    )
    cost = compute_cost_inr(usage, price_per_1m_inr=100.0, price_per_1m_out_inr=300.0)
    assert cost == pytest.approx(0.0)


# --- structuring confidence (issue #5) ------------------------------------------


def test_extract_confidence_reads_self_report() -> None:
    assert extract_confidence({"structuring_confidence": 0.82}) == pytest.approx(0.82)


def test_extract_confidence_clamps_into_range() -> None:
    assert extract_confidence({"structuring_confidence": 1.5}) == pytest.approx(1.0)
    assert extract_confidence({"structuring_confidence": -0.2}) == pytest.approx(0.0)


def test_extract_confidence_missing_or_invalid_is_none() -> None:
    assert extract_confidence({}) is None
    assert extract_confidence({"structuring_confidence": "oops"}) is None
