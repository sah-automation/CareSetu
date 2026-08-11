"""Phase 0 harness - NVIDIA NIM provider (issue #10).

Third candidate provider on the throwaway harness: NVIDIA NIM, driven over
the hosted OpenAI-compatible endpoint (``https://integrate.api.nvidia.com/v1``)
using httpx so the spike adds no new production dependency (same approach as
the Gemini and Whisper adapters). The pipeline is the 2-call path, mirroring
Whisper: transcribe over ``/v1/audio/transcriptions`` with the multilingual
``canary-1b-asr`` model (BCP-47 ``hi-IN``), then structure over
``/v1/chat/completions`` with a cheap catalog LLM and the same JSON field-set
prompt the other adapters use.

Cost posture: the hosted NIM preview is free for prototyping, so the list
price is zero and recorded INR is 0. Production use requires NVIDIA AI
Enterprise licensing, which is not a per-token published rate - that caveat is
recorded in the run output (``LICENSING_CAVEAT``). The ASR endpoint does not
report token counts, so transcription usage records 0 tokens (honest, not
estimated); the chat leg reports real tokens. Not production code.
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

_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
# The base URL already ends in /v1 (the OpenAI-compatible prefix), so the
# endpoint paths below are relative to it - never prefix them with /v1 again.
_ASR_ENDPOINT = "/audio/transcriptions"
_CHAT_ENDPOINT = "/chat/completions"
_TRANSIENT_STATUS_CODES = (500, 502, 503)
_QUOTA_STATUS_CODES = (429,)
_DEFAULT_RETRIES = 3
_DEFAULT_BACKOFF_SECONDS = 1.5
_DEFAULT_QUOTA_BACKOFF_SECONDS = 30.0
# Canary-1B supports hi-IN (BCP-47); the corpus is Hindi, matching the other
# adapters' Devanagari transcript prompt.
_LANGUAGE = "hi-IN"

LICENSING_CAVEAT = (
    "prototyping only - the hosted NVIDIA NIM preview is free for development; "
    "production use requires NVIDIA AI Enterprise licensing"
)

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
class NimPricing:
    """List-price table for the cost model.

    The hosted NIM preview is free (zero USD rates); production requires
    NVIDIA AI Enterprise licensing, which has no published per-token rate and
    is recorded as ``LICENSING_CAVEAT`` rather than folded into the cost model.
    """

    tier: str
    price_usd_per_1m_input: float
    price_usd_per_1m_output: float
    usd_to_inr: float

    @property
    def price_inr_per_1m_input(self) -> float:
        return self.price_usd_per_1m_input * self.usd_to_inr

    @property
    def price_inr_per_1m_output(self) -> float:
        return self.price_usd_per_1m_output * self.usd_to_inr


DEFAULT_PRICING = NimPricing(
    tier="prototyping",
    price_usd_per_1m_input=0.0,
    price_usd_per_1m_output=0.0,
    usd_to_inr=83.0,
)
DEFAULT_ASR_MODEL = "canary-1b-asr"
DEFAULT_CHAT_MODEL = "meta/llama-3.1-8b-instruct"


def _load_api_key(explicit: str | None) -> str:
    if explicit:
        return explicit
    from_env = os.environ.get("NVIDIA_API_KEY") or os.environ.get("NGC_API_KEY")
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
            if key.strip() == "NVIDIA_API_KEY" and value.strip():
                return value.strip().strip('"').strip("'")
    raise RuntimeError("NVIDIA_API_KEY is not set; export it or add it to the repo root .env")


def _model_from_env() -> str:
    return os.environ.get("NIM_ASR_MODEL", DEFAULT_ASR_MODEL)


def _chat_model_from_env() -> str:
    return os.environ.get("NIM_CHAT_MODEL", DEFAULT_CHAT_MODEL)


def _base_url_from_env() -> str:
    return os.environ.get("NIM_BASE_URL", _DEFAULT_BASE_URL)


def _auth_headers(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def build_transcribe_request(model: str, language: str) -> dict[str, str]:
    """The multipart form data for the audio → transcript step.

    ``response_format=json`` (the NIM default, set explicitly) returns
    ``{"text": "..."}``; unlike Whisper's ``verbose_json`` there is no
    ``duration`` field, so the per-second cost model does not apply here.
    """
    return {"model": model, "language": language, "response_format": "json"}


def parse_transcribe_response(response: dict[str, Any]) -> str:
    """Extract the transcript text from a NIM transcription response."""
    text = response.get("text")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("NIM returned no transcript text")
    return text


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
        raise RuntimeError(f"NIM API error{label}")
    if "detail" in response:
        raise RuntimeError("NIM API error")
    choices = response.get("choices")
    if not choices:
        raise RuntimeError("NIM returned no choices")
    first = choices[0]
    if first.get("finish_reason") not in (None, "stop"):
        raise RuntimeError(f"NIM stopped early: {first.get('finish_reason')}")
    content = first.get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("NIM returned empty message content")
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


class NimProvider:
    """NVIDIA NIM adapter (ASR + chat structuring) implementing the Gateway port."""

    name = "nim"

    def __init__(
        self,
        asr_model: str | None = None,
        chat_model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        pricing: NimPricing = DEFAULT_PRICING,
        timeout_seconds: float = 30.0,
        max_retries: int = _DEFAULT_RETRIES,
        retry_backoff_seconds: float = _DEFAULT_BACKOFF_SECONDS,
        quota_backoff_seconds: float = _DEFAULT_QUOTA_BACKOFF_SECONDS,
    ) -> None:
        self.model = asr_model or _model_from_env()
        self.chat_model = chat_model or _chat_model_from_env()
        self.api_key = _load_api_key(api_key)
        self.base_url = base_url or _base_url_from_env()
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
                        f"NIM HTTP {response.status_code} (response body withheld)"
                    )
                    await asyncio.sleep(self.quota_backoff_seconds)
                    continue
                if response.status_code in _TRANSIENT_STATUS_CODES:
                    last_error = RuntimeError(
                        f"NIM HTTP {response.status_code} (response body withheld)"
                    )
                    await asyncio.sleep(self.retry_backoff_seconds * (2**attempt))
                    continue
                raise RuntimeError(f"NIM HTTP {response.status_code} (response body withheld)")
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                await asyncio.sleep(self.retry_backoff_seconds * (2**attempt))
        raise RuntimeError(f"NIM request failed after {self.max_retries} attempts: {last_error}")

    async def transcribe(self, audio_path: Path, clip_id: str) -> TranscribeResult:
        mime = "audio/wav" if audio_path.suffix.lower() == ".wav" else "audio/mpeg"
        audio_bytes = audio_path.read_bytes()
        data = build_transcribe_request(self.model, _LANGUAGE)
        headers = _auth_headers(self.api_key)
        response = await self._post(
            lambda client: client.post(
                self.base_url + _ASR_ENDPOINT,
                headers=headers,
                files={"file": (audio_path.name, audio_bytes, mime)},
                data=data,
            )
        )
        text = parse_transcribe_response(response)
        # The ASR API does not report tokens, so they are recorded as 0 (honest,
        # not estimated); the preview list price is zero, so cost is 0.
        return TranscribeResult(
            text=text,
            usage=Usage(
                provider=self.name,
                model=self.model,
                input_tokens=0,
                output_tokens=0,
                cost_inr=0.0,
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
                self.base_url + _CHAT_ENDPOINT,
                headers=_auth_headers(self.api_key),
                json=payload,
            )
        )
        raw = parse_chat_content(response)
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise RuntimeError("NIM structure response was not a JSON object")
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
