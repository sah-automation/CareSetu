"""MOD-005: real EXT-002 provider adapter + config resolution (PHASE-7 T05 #348).

The staging/production implementation of the ``AiGateway`` port. It calls EXT-002
over HTTPS with the integration call discipline (third-party-integration-
standards §1): explicit timeout <= 30 s, up to 3 retries with exponential +
jitter backoff, and an in-process circuit breaker that fast-fails every call
while the provider is down. It is gated to staging/production by
``Settings.__post_init__`` (fail-closed): a real provider key is refused in
dev/test unless demo mode forces the mock, so the real EXT-002 path can never
run against a dev credential.

Only the intake context embedded in each request (``AiEgressContext`` plus the
transcript/audio being processed) is forwarded - never name, phone, or the full
record (NFR-SEC-006). ``sleep`` is injectable so tests can exercise the retry
loop without real waits; the API key is passed by the caller from ``Settings``,
never read from code or logs.

Outage failures are typed ``Ext002CallError(retries_exhausted=True)`` (network /
timeout / 429 / 5xx after the retry budget) and are the only events that trip
the circuit breaker; a 4xx contract rejection or a malformed payload is a
non-retryable ``Ext002CallError(retries_exhausted=False)`` that never trips it
(error-handling-observability §1, third-party-integration-standards §1).

The ``@observe`` annotations on the concrete LLM-calling methods (and the
breaker wrapper, which is part of the AI boundary) keep the pre-commit AI-
tracing gate (ai-engineering-standards A7) green.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx
from langfuse import observe

from app.config import (
    DEFAULT_AI_MAX_RETRIES,
    DEFAULT_AI_TIMEOUT_SECONDS,
    Settings,
)
from modules.intake.adapters.ai_gateway import (
    AiGateway,
    DraftRxRequest,
    DraftRxResult,
    StructureRequest,
    StructureResult,
    TranscribeRequest,
    TranscribeResult,
)
from modules.intake.adapters.ai_provider_mock import build_mock_ai_gateway

logger = logging.getLogger(__name__)

_TRANSCRIBE_PATH = "/v1/transcribe"
_STRUCTURE_PATH = "/v1/structure"
_DRAFT_RX_PATH = "/v1/draft-rx"


class Ext002CallError(RuntimeError):
    """A failed EXT-002 call, typed for the circuit breaker (error taxonomy).

    ``retries_exhausted`` separates genuine outages (network error, timeout,
    HTTP 429 / 5xx after the retry budget) - the only events that trip the
    breaker - from contract rejections (HTTP 4xx, malformed payload) that are
    the caller's problem and never trip it.
    """

    def __init__(self, message: str, *, retries_exhausted: bool) -> None:
        super().__init__(message)
        self.retries_exhausted = retries_exhausted


def _backoff_delay(attempt: int, base_seconds: float = 1.0) -> float:
    """Exponential backoff with jitter for retry ``attempt`` (1-based)."""
    if attempt < 1:
        return 0.0
    exponential = base_seconds * (1 << (attempt - 1))
    return exponential + random.uniform(0.0, exponential * 0.25)  # nosec B311


class Ext002AiProvider:
    """Staging/production EXT-002 implementation (httpx, timeout + retries).

    ``sleep`` is injectable so tests can exercise the retry loop without real
    waits. The API key is passed by the caller from ``Settings`` - never read
    from code or logs. Egress forwards only the request's intake context.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float = DEFAULT_AI_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_AI_MAX_RETRIES,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._sleep = sleep
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def _post_json(self, path: str, payload: dict[str, object]) -> dict[str, object]:
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_status = 0
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                await self._sleep(_backoff_delay(attempt))
            try:
                response = await self._client.post(
                    f"{self._base_url}{path}",
                    json=payload,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                if attempt == self._max_retries:
                    logger.error(
                        "EXT-002 %s failed after %d attempts (network error)",
                        path,
                        self._max_retries + 1,
                    )
                    raise Ext002CallError(
                        f"EXT-002 {path} failed after {self._max_retries + 1} attempts "
                        "(network error)",
                        retries_exhausted=True,
                    ) from exc
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last_status = response.status_code
                continue
            if response.is_success:
                try:
                    data = response.json()
                except ValueError as exc:
                    logger.error("EXT-002 %s returned a non-JSON response", path)
                    raise Ext002CallError(
                        f"EXT-002 {path} returned a non-JSON response",
                        retries_exhausted=False,
                    ) from exc
                if not isinstance(data, dict):
                    logger.error("EXT-002 %s returned an unexpected payload", path)
                    raise Ext002CallError(
                        f"EXT-002 {path} returned an unexpected payload",
                        retries_exhausted=False,
                    )
                return data
            logger.warning("EXT-002 %s rejected with HTTP %d", path, response.status_code)
            raise Ext002CallError(
                f"EXT-002 {path} rejected with HTTP {response.status_code}",
                retries_exhausted=False,
            )
        logger.error(
            "EXT-002 %s failed after %d attempts (last HTTP %d)",
            path,
            self._max_retries + 1,
            last_status,
        )
        raise Ext002CallError(
            f"EXT-002 {path} failed after {self._max_retries + 1} attempts "
            f"(last HTTP {last_status})",
            retries_exhausted=True,
        )

    @observe
    async def transcribe(self, request: TranscribeRequest) -> TranscribeResult:
        payload: dict[str, object] = {
            "audio_ref": request.audio_ref,
            "mode": request.mode,
            "language": request.context.language,
            "age_range": request.context.age_range,
            "sex": request.context.sex,
        }
        data = await self._post_json(_TRANSCRIBE_PATH, payload)
        return TranscribeResult.model_validate(data)

    @observe
    async def structure(self, request: StructureRequest) -> StructureResult:
        payload: dict[str, object] = {
            "transcript": request.transcript,
            "source": request.source,
            "language": request.context.language,
            "age_range": request.context.age_range,
            "sex": request.context.sex,
        }
        data = await self._post_json(_STRUCTURE_PATH, payload)
        return StructureResult.model_validate(data)

    @observe
    async def draft_rx(self, request: DraftRxRequest) -> DraftRxResult:
        payload: dict[str, object] = {
            "doctor_input_ref": request.doctor_input_ref,
            "pre_summary_ref": request.pre_summary_ref,
            "patient_history_summary": request.patient_history_summary,
            "language": request.context.language,
            "age_range": request.context.age_range,
            "sex": request.context.sex,
        }
        data = await self._post_json(_DRAFT_RX_PATH, payload)
        return DraftRxResult.model_validate(data)


_R = TypeVar("_R")


class CircuitBreakerAiGateway:
    """Wraps the real provider: fast-fails every call while it is down.

    An in-process circuit breaker so a provider outage never hammers EXT-002
    with a retry burst (third-party-integration-standards §1). While open, calls
    are refused until the cooldown elapses; the first call after the cooldown is
    the recovery probe - success closes the breaker, failure opens it again.
    Only genuine outage failures (``Ext002CallError(retries_exhausted=True)``)
    trip it - a contract rejection is the caller's problem and is never counted
    (error-handling-observability §1). The mock is never wrapped - this class
    exists only on the real provider path.
    """

    def __init__(
        self,
        adapter: Ext002AiProvider,
        *,
        threshold: int,
        cooldown_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._adapter = adapter
        self._threshold = threshold
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._open = False
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    def _allow(self) -> bool:
        if self._open and self._opened_at is not None:
            if self._clock() - self._opened_at >= self._cooldown_seconds:
                self._open = False
                return True
            return False
        return True

    def _record(self, ok: bool) -> None:
        if ok:
            self._consecutive_failures = 0
            self._open = False
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._threshold:
            self._open = True
            self._opened_at = self._clock()
            logger.warning(
                "EXT-002 circuit breaker opened after %d consecutive outage failures",
                self._consecutive_failures,
            )

    async def _run_with_breaker(self, name: str, fn: Awaitable[_R]) -> _R:
        if not self._allow():
            raise Ext002CallError(
                "EXT-002 circuit breaker is open; call refused without the provider",
                retries_exhausted=True,
            )
        try:
            result = await fn
        except Ext002CallError as exc:
            if exc.retries_exhausted:
                self._record(ok=False)
            raise
        self._record(ok=True)
        return result

    @observe
    async def transcribe(self, request: TranscribeRequest) -> TranscribeResult:
        return await self._run_with_breaker("transcribe", self._adapter.transcribe(request))

    @observe
    async def structure(self, request: StructureRequest) -> StructureResult:
        return await self._run_with_breaker("structure", self._adapter.structure(request))

    @observe
    async def draft_rx(self, request: DraftRxRequest) -> DraftRxResult:
        return await self._run_with_breaker("draft_rx", self._adapter.draft_rx(request))


def build_ai_gateway(settings: Settings) -> AiGateway:
    """Resolve the EXT-002 gateway from config; mock is the fail-closed default.

    ``Settings.__post_init__`` has already refused a real provider in dev/test
    (unless demo mode forced the mock), so reaching the provider branch here
    means a staging/production environment with a configured key. Only the real
    provider path is wrapped in the circuit breaker - the mock stays unwrapped.
    """
    provider = settings.ai_provider.strip().lower()
    if provider == "mock":
        return build_mock_ai_gateway()
    return CircuitBreakerAiGateway(
        Ext002AiProvider(
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        ),
        threshold=settings.ai_circuit_breaker_threshold,
        cooldown_seconds=settings.ai_circuit_breaker_cooldown_seconds,
    )


__all__ = [
    "CircuitBreakerAiGateway",
    "Ext002AiProvider",
    "Ext002CallError",
    "build_ai_gateway",
]
