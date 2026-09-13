"""MOD-005: config-driven EXT-002 gateway builder + circuit breaker (PHASE-7).

This module hosts the config-driven gateway builder (T04 #381):
``build_ai_gateway`` resolves the ``AiGateway`` port from ``Settings`` - mock
(unchanged default, unwrapped) or, for a real provider, an
``OpenAiCompatibleAdapter`` (T02 #379) wrapped in the circuit breaker, composed
into a primary + secondary ``FallbackAiGateway`` chain (T03 #380) when the
all-or-none fallback set is configured.

``CircuitBreakerAiGateway`` provides the in-process circuit breaker: while the
provider is down every call fast-fails without a retry burst
(third-party-integration-standards §1). It is reserved for the real-provider
path and never wraps the mock. Outage failures from the wire adapter
(``Ext002CallError(retries_exhausted=True)``, after network / timeout / 429 /
5xx exhaust the retry budget) are the only events that trip it; a 4xx contract
rejection or a malformed payload is a non-retryable ``Ext002CallError(
retries_exhausted=False)`` that never trips it (error-handling-observability §1).

Only the intake context embedded in each request (``AiEgressContext`` plus the
transcript/audio being processed) is ever forwarded - never name, phone, or the
full record (NFR-SEC-006). ``Settings.__post_init__`` gates a real provider key
to staging/production (fail-closed), so the real EXT-002 path can never run
against a dev credential unless ``AI_ALLOW_DEV_PROVIDER`` overrides the gate.

The ``@observe`` annotations on the breaker wrapper (which is part of the AI
boundary) keep the pre-commit AI-tracing gate (ai-engineering-standards A7)
green.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

from langfuse import observe

from app.config import Settings
from modules.intake.adapters.ai_gateway import (
    AiGateway,
    DraftRxRequest,
    DraftRxResult,
    Ext002CallError,
    StructureRequest,
    StructureResult,
    TranscribeRequest,
    TranscribeResult,
)
from modules.intake.adapters.ai_provider_fallback import AiGatewayMeta, FallbackAiGateway
from modules.intake.adapters.ai_provider_mock import build_mock_ai_gateway
from modules.intake.adapters.ai_provider_openai_compatible import OpenAiCompatibleAdapter

logger = logging.getLogger(__name__)


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
        adapter: AiGateway,
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

    @property
    def effective_provider(self) -> str | None:
        """Delegate the wrapped adapter's serving provider to the pipeline."""
        return self._adapter.effective_provider

    @property
    def effective_model(self) -> str | None:
        """Delegate the wrapped adapter's serving model to the pipeline."""
        return self._adapter.effective_model

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
    (unless demo mode forced the mock or ``AI_ALLOW_DEV_PROVIDER`` overrode the
    gate), so reaching the provider branch here means a staging/production
    environment with a configured key (or an explicit dev override). The registry
    is keyed on ``ai_provider`` in ``{"mock", "openai_compatible"}``:

    - ``mock`` -> the mock adapter, unchanged and NEVER wrapped in a breaker or
      fallback chain (its canned clean confidence would look like real structure).
    - ``openai_compatible`` -> an ``OpenAiCompatibleAdapter`` wrapped in the
      circuit breaker; when the all-or-none fallback set is configured, the
      breaker-wrapped primary and secondary are composed into a
      ``FallbackAiGateway`` that engages the secondary only on genuine outages.
    """
    provider = settings.ai_provider.strip().lower()
    if provider == "mock":
        return build_mock_ai_gateway()
    primary = CircuitBreakerAiGateway(
        OpenAiCompatibleAdapter(
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url,
            model=settings.ai_model,
            asr_model=settings.ai_asr_model,
            timeout_seconds=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
        ),
        threshold=settings.ai_circuit_breaker_threshold,
        cooldown_seconds=settings.ai_circuit_breaker_cooldown_seconds,
    )
    if settings.ai_fallback_provider.strip():
        secondary = CircuitBreakerAiGateway(
            OpenAiCompatibleAdapter(
                api_key=settings.ai_fallback_api_key,
                base_url=settings.ai_fallback_base_url,
                model=settings.ai_fallback_model,
                asr_model=settings.ai_asr_model,
                timeout_seconds=settings.ai_timeout_seconds,
                max_retries=settings.ai_max_retries,
            ),
            threshold=settings.ai_circuit_breaker_threshold,
            cooldown_seconds=settings.ai_circuit_breaker_cooldown_seconds,
        )
        return FallbackAiGateway(
            primary=primary,
            primary_meta=AiGatewayMeta(
                provider=provider,
                model=settings.ai_model,
            ),
            secondary=secondary,
            secondary_meta=AiGatewayMeta(
                provider=settings.ai_fallback_provider.strip().lower(),
                model=settings.ai_fallback_model,
            ),
        )
    return primary


__all__ = [
    "CircuitBreakerAiGateway",
    "Ext002CallError",
    "build_ai_gateway",
]
