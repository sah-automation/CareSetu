"""MOD-005: Fallback AI gateway composing primary + secondary providers (T03 #380).

A ``FallbackAiGateway`` composes two ``AiGateway`` instances - each already
wrapped in its own circuit breaker (T04 wiring) - into a primary/secondary
fallback chain. On a genuine outage failure (``Ext002CallError(retries_exhausted=
True)``) or an open primary breaker, the secondary is engaged. A contract
rejection (``retries_exhausted=False``) propagates immediately; the secondary is
never invoked for the same request bug.

Low structuring confidence never triggers fallback (ADR-0001): it remains the
forced-doctor-review signal.

After a successful call the effective provider + model are exposed via read-only
properties so pipeline bookkeeping (T04) can record which provider answered.
First successful provider wins; recovery is automatic because both underlying
breakers re-open and recovery-probe after their cooldowns. Engaging the
secondary is a degradation decision, so it is logged at warning level so
operators can see the fallback happened (third-party-integration-standards S2,
ai-engineering-standards A6; error-handling-observability S2).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from langfuse import observe

from modules.intake.adapters.ai_gateway import (
    AiGateway,
    DraftRxRequest,
    DraftRxResult,
    StructureRequest,
    StructureResult,
    TranscribeRequest,
    TranscribeResult,
)
from modules.intake.adapters.ai_provider_ext import Ext002CallError

logger = logging.getLogger(__name__)

_R = TypeVar("_R")


@dataclass(frozen=True)
class AiGatewayMeta:
    """Lightweight metadata carried per gateway for pipeline bookkeeping."""

    provider: str
    model: str


class FallbackAiGateway:
    """Primary + secondary fallback chain over two ``AiGateway`` instances.

    Each gateway is already wrapped in its own ``CircuitBreakerAiGateway`` by
    the builder (T04). This class does not own breaker state; it only routes
    between the two gateways based on the ``retries_exhausted`` flag on
    ``Ext002CallError``.

    ``last_effective_provider`` and ``last_effective_model`` are set after each
    successful call so pipeline code can read them cheaply.
    """

    def __init__(
        self,
        primary: AiGateway,
        primary_meta: AiGatewayMeta,
        secondary: AiGateway,
        secondary_meta: AiGatewayMeta,
    ) -> None:
        self._primary = primary
        self._primary_meta = primary_meta
        self._secondary = secondary
        self._secondary_meta = secondary_meta
        self._last_effective: AiGatewayMeta | None = None

    @property
    def last_effective_provider(self) -> str | None:
        return self._last_effective.provider if self._last_effective else None

    @property
    def last_effective_model(self) -> str | None:
        return self._last_effective.model if self._last_effective else None

    async def _route(
        self,
        primary_call: Callable[[], Awaitable[_R]],
        secondary_call: Callable[[], Awaitable[_R]],
    ) -> _R:
        """Try ``primary_call``; on a genuine outage fall back to ``secondary_call``.

        The routing decision is the ``retries_exhausted`` flag ONLY - a contract
        rejection (``False``) re-raises immediately and never invokes the
        secondary. A successful secondary call records it as the effective
        provider; when both legs fail on outage, the primary outage error is
        re-raised so operators see the originating failure.
        """
        try:
            result = await primary_call()
        except Ext002CallError as exc:
            if not exc.retries_exhausted:
                raise
            logger.warning(
                "EXT-002 primary provider outage (%s); engaging secondary fallback (%s)",
                self._primary_meta.provider,
                self._secondary_meta.provider,
            )
            primary_error = exc
            try:
                result = await secondary_call()
            except Ext002CallError as exc:
                raise primary_error from exc
        else:
            self._last_effective = self._primary_meta
            return result
        self._last_effective = self._secondary_meta
        return result

    @observe
    async def structure(self, request: StructureRequest) -> StructureResult:
        return await self._route(
            lambda: self._primary.structure(request),
            lambda: self._secondary.structure(request),
        )

    @observe
    async def transcribe(self, request: TranscribeRequest) -> TranscribeResult:
        return await self._route(
            lambda: self._primary.transcribe(request),
            lambda: self._secondary.transcribe(request),
        )

    @observe
    async def draft_rx(self, request: DraftRxRequest) -> DraftRxResult:
        return await self._route(
            lambda: self._primary.draft_rx(request),
            lambda: self._secondary.draft_rx(request),
        )


__all__ = [
    "AiGatewayMeta",
    "FallbackAiGateway",
]
