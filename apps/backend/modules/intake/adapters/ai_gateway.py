"""MOD-005: EXT-002 AI gateway port (standard A6, PHASE-7 T05 #348).

The single typed seam every LLM adapter satisfies. All LLM calls for the
transcribe -> structure -> pre-summary pipeline (and Phase 8's rx drafting)
flow through this port; domain code never touches a concrete provider. The
provider is selected by configuration (``ai_provider`` in ``Settings``), never
by code - swapping a provider is a new adapter, zero domain changes
(third-party-integration-standards §7).

The request models declare the **egress boundary** (``NFR-SEC-006``): a call to
EXT-002 may carry only intake context - the declared language, plus the
transcript/text (and the audio clip being transcribed) - never a patient's name,
phone, demographics, or the full record. ``AiEgressContext`` is the one
patient-shaped thing that may cross the wire, and it admits only the declared
language.

This module carries the DTOs, the typed ``Ext002CallError`` every adapter
raises, the shared retry plumbing (``_backoff_delay`` + ``post_with_backoff``),
and the abstract ``AiGateway`` protocol only; the concrete adapters (mock,
EXT-002 provider, OpenAI-compatible chat, fallback chain) live next to it and
implement the port. The protocol methods are abstract stubs, so no tracing is
required here - the concrete LLM-calling methods carry the ``@observe``
annotations where the concrete adapters are defined.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict

logger = logging.getLogger(__name__)

LANG_HI = "hi"
LANG_EN = "en"


def _backoff_delay(attempt: int, base_seconds: float = 1.0) -> float:
    """Exponential backoff with jitter for retry ``attempt`` (1-based).

    Package-internal retry helper shared by every EXT-002 adapter so the
    exponential + jitter curve is defined once (third-party-integration-
    standards §1).
    """
    if attempt < 1:
        return 0.0
    exponential = base_seconds * (1 << (attempt - 1))
    return exponential + random.uniform(0.0, exponential * 0.25)  # nosec B311


async def post_with_backoff(
    client: httpx.AsyncClient,
    url: str,
    *,
    json_body: dict[str, object] | None = None,
    data: dict[str, str] | None = None,
    files: dict[str, tuple[str, bytes, str]] | None = None,
    headers: dict[str, str],
    max_retries: int,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    label: str = "provider",
) -> dict[str, object]:
    """POST an EXT-002 endpoint with the shared retry/backoff discipline.

    The single implementation of the call-error loop every real provider
    adapter delegates to (PS-09, third-party-integration-standards §1). Accepts
    both call shapes the adapters post: a JSON body (``json_body``) and a
    ``multipart/form-data`` body (``data`` + ``files``). The caller supplies the
    :class:`httpx.AsyncClient`, which owns the ≤30 s client timeout; the helper
    enforces the exactly-``max_retries`` retry budget with exponential + jitter
    backoff (``_backoff_delay``) and an injectable ``sleep`` for tests.

    The typed outage-vs-contract split is preserved so the circuit breaker and
    fallback chain route correctly:

    - retryable (``Ext002CallError(retries_exhausted=True)`` on exhaustion):
      network errors, timeouts, HTTP 429, HTTP ≥ 500;
    - non-retryable (``retries_exhausted=False``, propagated immediately): HTTP
      4xx, a non-JSON success body, or a success body that is not a JSON object.

    ``label`` names the provider in logs and error messages so an outage is
    attributable to the serving adapter.
    """
    last_status = 0
    for attempt in range(max_retries + 1):
        if attempt > 0:
            await sleep(_backoff_delay(attempt))
        try:
            response = await client.post(
                url,
                json=json_body,
                data=data,
                files=files,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            if attempt == max_retries:
                logger.error(
                    "%s %s failed after %d attempts (network error)",
                    label,
                    url,
                    max_retries + 1,
                )
                raise Ext002CallError(
                    f"{label} {url} failed after {max_retries + 1} attempts (network error)",
                    retries_exhausted=True,
                ) from exc
            continue
        if response.status_code == 429 or response.status_code >= 500:
            last_status = response.status_code
            continue
        if response.is_success:
            try:
                body = response.json()
            except ValueError as exc:
                logger.error("%s %s returned a non-JSON response", label, url)
                raise Ext002CallError(
                    f"{label} {url} returned a non-JSON response",
                    retries_exhausted=False,
                ) from exc
            if not isinstance(body, dict):
                logger.error("%s %s returned an unexpected payload", label, url)
                raise Ext002CallError(
                    f"{label} {url} returned an unexpected payload",
                    retries_exhausted=False,
                )
            return body
        logger.warning("%s %s rejected with HTTP %d", label, url, response.status_code)
        raise Ext002CallError(
            f"{label} {url} rejected with HTTP {response.status_code}",
            retries_exhausted=False,
        )
    logger.error(
        "%s %s failed after %d attempts (last HTTP %d)",
        label,
        url,
        max_retries + 1,
        last_status,
    )
    raise Ext002CallError(
        f"{label} {url} failed after {max_retries + 1} attempts (last HTTP {last_status})",
        retries_exhausted=True,
    )


class AiEgressContext(BaseModel):
    """The only patient context allowed to leave MOD-005 (NFR-SEC-006).

    Egress to EXT-002 carries intake context only - the declared language, never
    a patient's name, phone, demographics, or the full record. Every request
    model that travels to the provider embeds exactly this. Unknown fields are
    rejected (fail-closed), never silently carried.
    """

    model_config = ConfigDict(extra="forbid")

    language: Literal["hi", "en"]


class TranscribeRequest(BaseModel):
    """Input to the transcribe leg: one intake audio clip plus minimal context.

    ``audio_bytes`` is the decrypted clip sent to the ASR provider (the
    patient's own words, expected by the transcribe leg - within the egress
    boundary as the clip itself). ``audio_ref`` is the pseudonymous reference to
    the intake media, carried for the proxy-style adapter and audit, not a
    patient identifier. The patient-shaped context is bounded to
    ``AiEgressContext``; extra fields are rejected (fail-closed).
    """

    model_config = ConfigDict(extra="forbid")

    audio_ref: str
    audio_bytes: bytes | None = None
    mode: Literal["voice"]
    context: AiEgressContext


class TranscribeResult(BaseModel):
    """The transcript plus the provider's measured transcription confidence.

    ``input_tokens`` / ``output_tokens`` are the provider's reported usage for
    the call (default 0 - the metering seam (PS-01) so downstream bookkeeping
    can record real costs; the OpenAI-compatible adapter reports the real
    numbers, the mock and fallback paths report real 0).
    """

    transcript: str
    confidence: float
    language: Literal["hi", "en"]
    input_tokens: int = 0
    output_tokens: int = 0


class StructureRequest(BaseModel):
    """Input to the structure leg: the transcribed text plus minimal context."""

    model_config = ConfigDict(extra="forbid")

    transcript: str
    source: Literal["voice", "text"]
    context: AiEgressContext


class StructureResult(BaseModel):
    """The structured clinical fields plus provider self-reported confidence.

    ``confidence`` is the provider's ``structuring_confidence`` (ADR-0001 /
    glossary): compared against the 0.70 threshold downstream to derive the
    ``low_confidence`` flag and force doctor review when below.
    ``input_tokens`` / ``output_tokens`` carry the provider's reported usage
    (default 0) for metering (PS-01).
    """

    chief_complaints: list[str]
    symptoms: list[str]
    duration: str
    confidence: float
    input_tokens: int = 0
    output_tokens: int = 0


class DraftRxRequest(BaseModel):
    """Phase 8 contract-only input to the rx-drafting leg (declared now).

    Carries only reference ids plus the patient history summary - the drafting
    input, never name/phone/full record (NFR-SEC-006). This leg becomes live in
    Phase 8; the port declares the contract before any caller uses it. Extra
    fields are rejected (fail-closed).
    """

    model_config = ConfigDict(extra="forbid")

    doctor_input_ref: str
    pre_summary_ref: str
    patient_history_summary: str
    context: AiEgressContext


class RxItem(BaseModel):
    """One drafted prescription line (name, dose, duration)."""

    name: str
    dose: str
    duration: str


class DraftRxResult(BaseModel):
    """The drafted prescription lines plus provider confidence.

    ``input_tokens`` / ``output_tokens`` carry the provider's reported usage
    (default 0) for metering (PS-01).
    """

    rx_items: list[RxItem]
    confidence: float
    input_tokens: int = 0
    output_tokens: int = 0


class Ext002CallError(RuntimeError):
    """A failed EXT-002 call, typed for the circuit breaker (error taxonomy).

    ``retries_exhausted`` separates genuine outages (network error, timeout,
    HTTP 429/5xx after the retry budget) - the only events that trip the
    breaker - from contract rejections (HTTP 4xx, malformed payload) that are
    the caller's problem and never trip it. Owned by the port so every adapter
    (EXT-002 provider, OpenAI-compatible chat, fallback chain) raises and
    routes on the same typed error.
    """

    def __init__(self, message: str, *, retries_exhausted: bool) -> None:
        super().__init__(message)
        self.retries_exhausted = retries_exhausted


class AiGateway(Protocol):
    """Port every EXT-002 adapter satisfies (A6) - the three egress operations.

    Abstract by declaration; concrete adapters implement each operation and own
    the tracing (``@observe``) on the methods that make the LLM call.

    ``effective_provider`` / ``effective_model`` expose the provider that
    actually served the most recent successful call so pipeline bookkeeping can
    record reality. On the fallback chain they are ``None`` until the first
    success; on the mock and single-provider paths the values are static and
    always set.
    """

    @property
    def effective_provider(self) -> str | None: ...

    @property
    def effective_model(self) -> str | None: ...

    async def transcribe(self, request: TranscribeRequest) -> TranscribeResult: ...

    async def structure(self, request: StructureRequest) -> StructureResult: ...

    async def draft_rx(self, request: DraftRxRequest) -> DraftRxResult: ...


__all__ = [
    "LANG_EN",
    "LANG_HI",
    "AiEgressContext",
    "AiGateway",
    "DraftRxRequest",
    "DraftRxResult",
    "Ext002CallError",
    "RxItem",
    "StructureRequest",
    "StructureResult",
    "TranscribeRequest",
    "TranscribeResult",
    "post_with_backoff",
]
