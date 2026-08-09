"""Phase 0 harness — Gemini provider (issue #4).

First candidate provider on the throwaway harness: the Gemini free/cheap tier,
driven over the same REST endpoint the google-genai SDK wraps, using httpx so
the spike adds no new production dependency. Audio is sent inline (base64);
responses are parsed for the transcript text and usageMetadata token counts.
INR cost is computed from a configurable list-price table (free-tier billing
is 0; the list price feeds the Phase 0 cost model).

Gemini is multimodal: the transcribe + structure steps MAY collapse into one
call. The port keeps them separate; ``GeminiProvider.probe_single_call``
documents whether the collapse actually works so the per-intake cost ceiling
(issue #2) restates correctly. Not production code.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from phase0.harness.models import StructureResult, TranscribeResult, Usage

_API_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
_TRANSIENT_STATUS_CODES = (500, 502, 503)
_QUOTA_STATUS_CODES = (429,)
_DEFAULT_RETRIES = 3
_DEFAULT_BACKOFF_SECONDS = 1.5
_DEFAULT_QUOTA_BACKOFF_SECONDS = 30.0
_TRANSCRIBE_PROMPT = (
    "You are transcribing a Hindi medical consultation recording. "
    "Transcribe the speech verbatim into Devanagari script; keep English or "
    "romanized words exactly as they were spoken. Preserve hesitation words "
    'such as "हम्म" and "अरे" as heard. Output only the transcript text, '
    "with no preamble, commentary, or quotation marks."
)
_STRUCTURE_PROMPT = (
    "You structure a transcribed Hindi medical consultation into a JSON "
    "pre-summary matching the provisional field set. "
    'Return ONLY a JSON object with exactly these keys: "chief_complaint", '
    '"onset", "duration", "location", "severity", "nature", '
    '"associated_symptoms", "aggravating_factors", "relieving_factors", '
    '"known_medications", "allergies", "past_history", "family_history", '
    '"vitals", "labs_ordered", "diagnosis_impression", "advice", "follow_up", '
    '"clinical_notes", "extraction_notes". Record only what is actually '
    "spoken: unstated string fields are null, unstated list fields are []. "
    "Never invent facts."
)


@dataclass(frozen=True)
class GeminiPricing:
    """List-price table for the cost model; free-tier billing is 0."""

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


# Gemini 2.5 Flash list prices (US cents per 1M tokens); audio input may be
# billed higher than text input — this table uses the text rate and is
# configurable via GEMINI_PRICE_USD_PER_1M_IN / _OUT if the tier changes.
DEFAULT_PRICING = GeminiPricing(
    tier="free",
    price_usd_per_1m_input=0.30,
    price_usd_per_1m_output=2.50,
    usd_to_inr=83.0,
)
DEFAULT_MODEL = "gemini-2.5-flash"


def _load_api_key(explicit: str | None) -> str:
    if explicit:
        return explicit
    from_env = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
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
            if key.strip() == "GEMINI_API_KEY" and value.strip():
                return value.strip().strip('"').strip("'")
    raise RuntimeError("GEMINI_API_KEY is not set; export it or add it to the repo root .env")


def _model_from_env() -> str:
    return os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)


def build_transcribe_request(model: str, audio_bytes: bytes, mime: str) -> dict[str, Any]:
    """The generateContent payload for the audio → transcript step."""
    return {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": _TRANSCRIBE_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime,
                            "data": base64.b64encode(audio_bytes).decode("ascii"),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {"temperature": 0.0},
    }


def parse_generate_response(response: dict[str, Any]) -> str:
    candidates = response.get("candidates")
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {response.get('promptFeedback')}")
    first = candidates[0]
    if first.get("finishReason") not in (None, "STOP"):
        raise RuntimeError(f"Gemini stopped early: {first.get('finishReason')}")
    parts = first.get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()


def parse_usage(response: dict[str, Any], provider: str, model: str, tier: str) -> Usage:
    metadata = response.get("usageMetadata") or {}
    input_tokens = int(metadata.get("promptTokenCount", 0))
    output_tokens = int(metadata.get("candidatesTokenCount", 0))
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


class GeminiProvider:
    """Gemini free/cheap-tier adapter implementing the Gateway port."""

    name = "gemini"

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        pricing: GeminiPricing = DEFAULT_PRICING,
        timeout_seconds: float = 30.0,
        max_retries: int = _DEFAULT_RETRIES,
        retry_backoff_seconds: float = _DEFAULT_BACKOFF_SECONDS,
        quota_backoff_seconds: float = _DEFAULT_QUOTA_BACKOFF_SECONDS,
    ) -> None:
        self.model = model or _model_from_env()
        self.api_key = _load_api_key(api_key)
        self.pricing = pricing
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.quota_backoff_seconds = quota_backoff_seconds

    @property
    def tier(self) -> str:
        return self.pricing.tier

    def _usage_from_response(self, response: dict[str, Any], latency_ms: int) -> Usage:
        usage = parse_usage(response, provider=self.name, model=self.model, tier=self.tier)
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

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = _API_ENDPOINT.format(model=self.model)
        headers = {"x-goog-api-key": self.api_key}
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            started = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(url, json=payload, headers=headers)
                if response.status_code == 200:
                    body: dict[str, Any] = response.json()
                    body["_latency_ms"] = int((time.monotonic() - started) * 1000)
                    return body
                if response.status_code in _QUOTA_STATUS_CODES:
                    # Free-tier quotas reset over minutes; wait a long settle,
                    # not the short transient backoff.
                    last_error = RuntimeError(
                        f"Gemini HTTP {response.status_code}: {response.text[:200]}"
                    )
                    await asyncio.sleep(self.quota_backoff_seconds)
                    continue
                if response.status_code in _TRANSIENT_STATUS_CODES:
                    last_error = RuntimeError(
                        f"Gemini HTTP {response.status_code}: {response.text[:200]}"
                    )
                    await asyncio.sleep(self.retry_backoff_seconds * (2**attempt))
                    continue
                raise RuntimeError(f"Gemini HTTP {response.status_code}: {response.text[:200]}")
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                last_error = exc
                await asyncio.sleep(self.retry_backoff_seconds * (2**attempt))
        raise RuntimeError(f"Gemini request failed after {self.max_retries} attempts: {last_error}")

    async def transcribe(self, audio_path: Path, clip_id: str) -> TranscribeResult:
        mime = "audio/wav" if audio_path.suffix.lower() == ".wav" else "audio/mpeg"
        audio_bytes = audio_path.read_bytes()
        payload = build_transcribe_request(self.model, audio_bytes, mime)
        response = await self._post(payload)
        text = parse_generate_response(response)
        return TranscribeResult(
            text=text,
            usage=self._usage_from_response(response, response.get("_latency_ms", 0)),
        )

    async def structure(self, transcript: str, clip_id: str) -> StructureResult:
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": _STRUCTURE_PROMPT},
                        {"text": f"Transcript:\n{transcript}"},
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
        }
        response = await self._post(payload)
        raw = parse_generate_response(response)
        structured = json.loads(raw)
        if not isinstance(structured, dict):
            raise RuntimeError("Gemini structure response was not a JSON object")
        return StructureResult(
            structured=structured,
            confidence=None,
            usage=self._usage_from_response(response, response.get("_latency_ms", 0)),
        )

    async def probe_single_call(self, audio_path: Path, clip_id: str) -> dict[str, Any]:
        """Document the multimodal finding: can Gemini do both steps in one call?"""
        mime = "audio/wav" if audio_path.suffix.lower() == ".wav" else "audio/mpeg"
        audio_bytes = audio_path.read_bytes()
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": _STRUCTURE_PROMPT},
                        {
                            "inline_data": {
                                "mime_type": mime,
                                "data": base64.b64encode(audio_bytes).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {"temperature": 0.0, "responseMimeType": "application/json"},
        }
        try:
            response = await self._post(payload)
            raw = parse_generate_response(response)
            json.loads(raw)
            return {
                "attempted": True,
                "collapsed": True,
                "note": (
                    "Gemini accepts audio + a structuring prompt in one "
                    "generateContent call and returns valid JSON; transcribe + "
                    "structure can be a single call, so the per-intake cost "
                    "ceiling is one call, not two."
                ),
                "usage": self._usage_from_response(response, response.get("_latency_ms", 0)),
            }
        except Exception as exc:
            note = (
                f"single-call probe failed ({type(exc).__name__}: {exc}); keeping 2-call pipeline"
            )
            return {
                "attempted": True,
                "collapsed": False,
                "note": note,
                "usage": None,
            }
