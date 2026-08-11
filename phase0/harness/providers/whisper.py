"""Phase 0 harness - OpenAI Whisper provider (issue #9).

Second candidate provider on the throwaway harness: OpenAI Whisper
(``whisper-1``) for the audio → transcript leg, driven over the REST API
using httpx so the spike adds no new production dependency (same approach as
the Gemini adapter). Whisper is ASR-only, so the pipeline is the 2-call path:
transcribe over ``/v1/audio/transcriptions`` (multipart, ``language=hi``),
then structure over ``/v1/chat/completions`` with a cheap chat model and the
same JSON field-set prompt the Gemini adapter uses.

Whisper's published pricing is per-second for transcription and per-token for
the chat structuring leg; the list price feeds the Phase 0 cost model and is
configurable, matching the Gemini adapter's tier vocabulary. The transcription
API does not report token counts, so ASR usage records 0 tokens (honest, not
estimated) and its INR cost is computed from the audio duration returned by
the provider. Not production code.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

from phase0.harness.models import PreSummaryData, StructureResult, TranscribeResult, Usage

_TRANSCRIBE_ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"
_STRUCTURE_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_TRANSIENT_STATUS_CODES = (500, 502, 503)
_QUOTA_STATUS_CODES = (429,)
_DEFAULT_RETRIES = 3
_DEFAULT_BACKOFF_SECONDS = 1.5
_DEFAULT_QUOTA_BACKOFF_SECONDS = 30.0
# The corpus is Hindi; whisper-1 transcribes in the explicitly requested
# language, matching the Gemini adapter's Devanagari transcript prompt.
_LANGUAGE = "hi"

_STRUCTURE_PROMPT = (
    "You structure a transcribed Hindi medical consultation into a JSON "
    "pre-summary matching the provisional field set. "
    'Return ONLY a JSON object with exactly these keys: "chief_complaint", '
    '"onset", "duration", "location", "severity", "nature", '
    '"associated_symptoms", "aggravating_factors", "relieving_factors", '
    '"known_medications", "allergies", "past_history", "family_history", '
    '"vitals", "labs_ordered", "diagnosis_impression", "advice", "follow_up", '
    '"clinical_notes", "extraction_notes", "structuring_confidence". Record '
    "only what is actually spoken: unstated string fields are null, unstated "
    'list fields are []. Never invent facts. "structuring_confidence" is a '
    "number from 0 to 1 stating how confident you are that the extraction "
    "captures everything stated in the transcript and nothing else - lower it "
    "when fields are ambiguous, partially stated, or the transcript is noisy. "
    "It is the AMB-006 calibration signal, so do not game it."
)


@dataclass(frozen=True)
class WhisperPricing:
    """List-price table for the cost model.

    ``price_usd_per_second`` covers the ASR leg (whisper-1 bills per audio
    second); the per-1M-token rates cover the chat structuring leg. USD prices
    are converted to INR so both legs report ``cost_inr`` like Gemini.
    """

    tier: str
    price_usd_per_second: float
    price_usd_per_1m_input: float
    price_usd_per_1m_output: float
    usd_to_inr: float

    @property
    def price_inr_per_second(self) -> float:
        return self.price_usd_per_second * self.usd_to_inr

    @property
    def price_inr_per_1m_input(self) -> float:
        return self.price_usd_per_1m_input * self.usd_to_inr

    @property
    def price_inr_per_1m_output(self) -> float:
        return self.price_usd_per_1m_output * self.usd_to_inr


# Published list prices: whisper-1 = $0.006 / minute (i.e. $0.0001 / second);
# the structuring leg uses gpt-4o-mini per-token rates. All configurable if the
# tier or models change.
DEFAULT_PRICING = WhisperPricing(
    tier="paid",
    price_usd_per_second=0.0001,
    price_usd_per_1m_input=0.15,
    price_usd_per_1m_output=0.60,
    usd_to_inr=83.0,
)
DEFAULT_MODEL = "whisper-1"
DEFAULT_CHAT_MODEL = "gpt-4o-mini"


def _load_api_key(explicit: str | None) -> str:
    if explicit:
        return explicit
    from_env = os.environ.get("OPENAI_API_KEY")
    if from_env:
        return from_env
    # Fall back to the repo's .env (never committed) when not exported.
    dotenv = Path(__file__).resolve().parents[3] / ".env"
    if dotenv.is_file():
        for line in dotenv.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key.strip() == "OPENAI_API_KEY" and value.strip():
                return value.strip().strip('"').strip("'")
    raise RuntimeError("OPENAI_API_KEY is not set; export it or add it to the repo root .env")


def _model_from_env() -> str:
    return os.environ.get("WHISPER_MODEL", DEFAULT_MODEL)


def _chat_model_from_env() -> str:
    return os.environ.get("WHISPER_CHAT_MODEL", DEFAULT_CHAT_MODEL)


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def build_transcribe_request(model: str, language: str) -> dict[str, str]:
    """The multipart form data for the audio → transcript step.

    ``verbose_json`` (not the default ``json``) is required: only it returns
    the ``duration`` field the per-second cost model needs.
    """
    return {"model": model, "language": language, "response_format": "verbose_json"}


def parse_transcribe_response(response: dict[str, Any]) -> tuple[str, float]:
    """Extract the transcript text and audio duration from a transcription response."""
    text = response.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("OpenAI returned no transcript text")
    duration_value = response.get("duration")
    if duration_value is None:
        return text, 0.0
    try:
        duration_seconds = float(duration_value)
    except (TypeError, ValueError):
        duration_seconds = 0.0
    return text, duration_seconds


def parse_chat_content(response: dict[str, Any]) -> str:
    """Extract the assistant message content from a chat completions response."""
    if "error" in response:
        # Redact free text: the provider payload may carry PHI
        # (error-handling-observability §2). Keep only non-PHI metadata.
        meta = response["error"]
        label = ""
        if isinstance(meta, dict):
            bits = [
                str(part)
                for part in (meta.get("type"), meta.get("code"))
                if isinstance(part, str) and part
            ]
            if bits:
                label = f" ({', '.join(bits)})"
        raise RuntimeError(f"OpenAI API error{label}")
    choices = response.get("choices")
    if not choices:
        # No raw payload here: the response body derives from the transcript
        # and may carry PHI (error-handling-observability §2).
        raise RuntimeError("OpenAI returned no choices")
    first = choices[0]
    if first.get("finish_reason") not in (None, "stop"):
        raise RuntimeError(f"OpenAI stopped early: {first.get('finish_reason')}")
    content = first.get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenAI returned empty message content")
    return content


def parse_chat_usage(response: dict[str, Any], provider: str, model: str, tier: str) -> Usage:
    metadata = response.get("usage") or {}
    input_tokens = int(metadata.get("prompt_tokens", 0))
    output_tokens = int(metadata.get("completion_tokens", 0))
    return Usage(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_inr=0.0,
        latency_ms=0,
        tier=tier,
    )


def compute_transcription_cost_inr(duration_seconds: float, price_inr_per_second: float) -> float:
    """ASR cost at the per-second list price (tokens are not reported)."""
    return duration_seconds * price_inr_per_second


def compute_cost_inr(usage: Usage, price_per_1m_inr: float, price_per_1m_out_inr: float) -> float:
    numerator = usage.input_tokens * price_per_1m_inr + usage.output_tokens * price_per_1m_out_inr
    return numerator / 1_000_000


def extract_confidence(structured: dict[str, Any]) -> float | None:
    """Read the model's self-reported structuring confidence (0..1).

    Clamped into range; missing or non-numeric values become ``None``, which
    the AMB-006 flag treats as low confidence (untrustworthy).
    """
    value = structured.get("structuring_confidence")
    if value is None:
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    return min(1.0, max(0.0, confidence))


class WhisperProvider:
    """OpenAI Whisper adapter (ASR + chat structuring) implementing the Gateway port."""

    name = "whisper"

    def __init__(
        self,
        model: str | None = None,
        chat_model: str | None = None,
        api_key: str | None = None,
        pricing: WhisperPricing = DEFAULT_PRICING,
        timeout_seconds: float = 30.0,
        max_retries: int = _DEFAULT_RETRIES,
        retry_backoff_seconds: float = _DEFAULT_BACKOFF_SECONDS,
        quota_backoff_seconds: float = _DEFAULT_QUOTA_BACKOFF_SECONDS,
    ) -> None:
        self.model = model or _model_from_env()
        self.chat_model = chat_model or _chat_model_from_env()
        self.api_key = _load_api_key(api_key)
        self.pricing = pricing
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.quota_backoff_seconds = quota_backoff_seconds

    @property
    def tier(self) -> str:
        return self.pricing.tier

    def _chat_usage_from_response(self, response: dict[str, Any], latency_ms: int) -> Usage:
        usage = parse_chat_usage(
            response, provider=self.name, model=self.chat_model, tier=self.tier
        )
        cost = compute_cost_inr(
            usage,
            self.pricing.price_inr_per_1m_input,
            self.pricing.price_inr_per_1m_output,
        )
        return Usage(
            provider=usage.provider,
            model=usage.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cost_inr=round(cost, 6),
            latency_ms=latency_ms,
            tier=usage.tier,
        )

    async def _post(
        self, send: Callable[[httpx.AsyncClient], Awaitable[httpx.Response]]
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            started = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await send(client)
                if response.status_code == 200:
                    body: dict[str, Any] = response.json()
                    body["_latency_ms"] = int((time.monotonic() - started) * 1000)
                    return body
                if response.status_code in _QUOTA_STATUS_CODES:
                    # Rate limits reset over minutes; wait a long settle, not
                    # the short transient backoff.
                    last_error = RuntimeError(
                        f"OpenAI HTTP {response.status_code} (response body withheld)"
                    )
                    await asyncio.sleep(self.quota_backoff_seconds)
                    continue
                if response.status_code in _TRANSIENT_STATUS_CODES:
                    last_error = RuntimeError(
                        f"OpenAI HTTP {response.status_code} (response body withheld)"
                    )
                    await asyncio.sleep(self.retry_backoff_seconds * (2**attempt))
                    continue
                raise RuntimeError(f"OpenAI HTTP {response.status_code} (response body withheld)")
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                await asyncio.sleep(self.retry_backoff_seconds * (2**attempt))
        raise RuntimeError(f"OpenAI request failed after {self.max_retries} attempts: {last_error}")

    async def transcribe(self, audio_path: Path, clip_id: str) -> TranscribeResult:
        mime = "audio/wav" if audio_path.suffix.lower() == ".wav" else "audio/mpeg"
        audio_bytes = audio_path.read_bytes()
        data = build_transcribe_request(self.model, _LANGUAGE)
        headers = _auth_headers(self.api_key)
        response = await self._post(
            lambda client: client.post(
                _TRANSCRIBE_ENDPOINT,
                headers=headers,
                files={"file": (audio_path.name, audio_bytes, mime)},
                data=data,
            )
        )
        text, duration_seconds = parse_transcribe_response(response)
        cost = compute_transcription_cost_inr(duration_seconds, self.pricing.price_inr_per_second)
        return TranscribeResult(
            text=text,
            usage=Usage(
                provider=self.name,
                model=self.model,
                input_tokens=0,
                output_tokens=0,
                cost_inr=round(cost, 6),
                latency_ms=response.get("_latency_ms", 0),
                tier=self.tier,
            ),
        )

    async def structure(self, transcript: str, clip_id: str) -> StructureResult:
        payload: dict[str, Any] = {
            "model": self.chat_model,
            "messages": [
                {"role": "user", "content": f"{_STRUCTURE_PROMPT}\n\nTranscript:\n{transcript}"}
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        response = await self._post(
            lambda client: client.post(
                _STRUCTURE_ENDPOINT, headers=_auth_headers(self.api_key), json=payload
            )
        )
        raw = parse_chat_content(response)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError("OpenAI structure response was not a JSON object")
        # structuring_confidence is the AMB-006 signal, not a field-set field.
        confidence = extract_confidence(parsed)
        parsed.pop("structuring_confidence", None)
        # The field-set shape is asserted, not validated: scoring treats missing
        # keys as empty, and the runner flags a response with no field-set keys.
        structured = cast(PreSummaryData, parsed)
        return StructureResult(
            structured=structured,
            confidence=confidence,
            usage=self._chat_usage_from_response(response, response.get("_latency_ms", 0)),
        )
