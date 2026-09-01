"""MOD-010: EXT-003 WhatsApp/partner notification adapter (T11, ticket #246).

One typed send operation behind a ``ChannelAdapter`` (``transport.DeliveryRequest``).
The mock implementation is the CI/local-dev default: it records the sent body per
phone for tests and never logs it. The provider implementation is the same
interface and is gated to staging/production by ``Settings`` (``__post_init__``),
keeping the real EXT-003 path out of dev/test.

EXT-003 call discipline (third-party-integration-standards §1): timeout <= 10 s,
up to 3 retries (4 total attempts) with exponential + jitter, an in-process
circuit breaker (``CircuitBreaker``) that fast-fails every send while a provider
outage persists and probes recovery after a cooldown, server-side API key from
settings only, and the message body never reaches a log line. Only genuine
outage failures (network/timeout/5xx/429,
``NotificationDeliveryError(retries_exhausted=True)``) trip the breaker - a 4xx
contract rejection never does.

The send/retry/parse pipeline lives in ``transport.HttpProviderChannel``; this
module supplies only the EXT-003-specific bits: integration label, send path,
and defaults.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

from app.config import (
    DEFAULT_WHATSAPP_MAX_RETRIES,
    DEFAULT_WHATSAPP_TIMEOUT_SECONDS,
    Settings,
)
from modules.notify.adapters.transport import (
    ChannelAdapter,
    CircuitBreaker,
    CircuitBreakerChannel,
    HttpProviderChannel,
    MockChannel,
)


class MockWhatsAppChannel(MockChannel):
    """CI/dev implementation: records sent messages for tests, never logs them."""

    def __init__(self) -> None:
        super().__init__(request_id_prefix="mock-wa-")


class WhatsAppProviderChannel(HttpProviderChannel):
    """Staging/production EXT-003 implementation (httpx, timeout + retries).

    ``sleep`` is injectable so tests can exercise the retry loop without real
    waits. The API key is passed by the caller from ``Settings`` - never read
    from code or logs.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float = DEFAULT_WHATSAPP_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_WHATSAPP_MAX_RETRIES,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(
            integration_label="EXT-003 WhatsApp",
            send_path="/v1/send",
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            client=client,
            sleep=sleep,
        )


def build_whatsapp_channel(settings: Settings) -> ChannelAdapter:
    """Resolve the EXT-003 channel from config; mock is the CI/dev default.

    Only the provider branch is wrapped in the circuit breaker - the mock stays
    unwrapped so dev/E2E sends are never fast-failed.
    """
    provider = settings.whatsapp_provider.strip().lower()
    if provider == "mock":
        return MockWhatsAppChannel()
    return CircuitBreakerChannel(
        WhatsAppProviderChannel(
            api_key=settings.whatsapp_api_key,
            base_url=settings.whatsapp_base_url,
            timeout_seconds=settings.whatsapp_timeout_seconds,
            max_retries=settings.whatsapp_max_retries,
        ),
        CircuitBreaker(
            integration="EXT-003",
            threshold=settings.whatsapp_circuit_breaker_threshold,
            cooldown_seconds=settings.whatsapp_circuit_breaker_cooldown_seconds,
        ),
    )


__all__ = [
    "MockWhatsAppChannel",
    "WhatsAppProviderChannel",
    "build_whatsapp_channel",
]
