"""MOD-010: EXT-001 SMS adapter for partner notifications (T11, ticket #246).

The notify module's own SMS port (module isolation per coding-standards §2 -
it must not import the iam SMS adapter, only model itself on it). It reuses the
shared EXT-001 ``sms_*`` ``Settings`` knobs (the integration is shared beyond
OTP) while owning its port contract and this file.

One typed send operation behind a ``ChannelAdapter`` (``transport.DeliveryRequest``).
The mock implementation is the CI/local-dev default: it records the sent body per
phone for tests and never logs it. The provider implementation is the same
interface and is gated to staging/production by ``Settings`` (``__post_init__``),
keeping the real EXT-001 path out of dev/test.

EXT-001 call discipline (third-party-integration-standards §1): timeout <= 10 s,
up to 3 retries (4 total attempts) with exponential + jitter, an in-process
circuit breaker (``CircuitBreaker``) that fast-fails every send while a provider
outage persists and probes recovery after a cooldown, server-side API key from
settings only, and the message body never reaches a log line. Only genuine
outage failures (network/timeout/5xx/429,
``NotificationDeliveryError(retries_exhausted=True)``) trip the breaker - a 4xx
contract rejection never does.

The send/retry/parse pipeline lives in ``transport.HttpProviderChannel``; this
module supplies only the EXT-001-specific bits: integration label, send path,
and defaults.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

from app.config import (
    DEFAULT_SMS_MAX_RETRIES,
    DEFAULT_SMS_TIMEOUT_SECONDS,
    Settings,
)
from modules.notify.adapters.transport import (
    ChannelAdapter,
    CircuitBreaker,
    CircuitBreakerChannel,
    HttpProviderChannel,
    MockChannel,
)


class MockNotifySmsChannel(MockChannel):
    """CI/dev implementation: records sent messages for tests, never logs them."""

    def __init__(self) -> None:
        super().__init__(request_id_prefix="mock-sms-")


class NotifySmsProviderChannel(HttpProviderChannel):
    """Staging/production EXT-001 implementation (httpx, timeout + retries).

    ``sleep`` is injectable so tests can exercise the retry loop without real
    waits. The API key is passed by the caller from ``Settings`` - never read
    from code or logs.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        timeout_seconds: float = DEFAULT_SMS_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_SMS_MAX_RETRIES,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        super().__init__(
            integration_label="EXT-001 SMS",
            send_path="/v1/send",
            api_key=api_key,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            client=client,
            sleep=sleep,
        )


def build_notify_sms_channel(settings: Settings) -> ChannelAdapter:
    """Resolve the EXT-001 channel from config; mock is the CI/dev default.

    Only the provider branch is wrapped in the circuit breaker - the mock stays
    unwrapped so dev/E2E sends are never fast-failed.
    """
    provider = settings.sms_provider.strip().lower()
    if provider == "mock":
        return MockNotifySmsChannel()
    return CircuitBreakerChannel(
        NotifySmsProviderChannel(
            api_key=settings.sms_api_key,
            base_url=settings.sms_base_url,
            timeout_seconds=settings.sms_timeout_seconds,
            max_retries=settings.sms_max_retries,
        ),
        CircuitBreaker(
            integration="EXT-001",
            threshold=settings.sms_circuit_breaker_threshold,
            cooldown_seconds=settings.sms_circuit_breaker_cooldown_seconds,
        ),
    )


__all__ = [
    "MockNotifySmsChannel",
    "NotifySmsProviderChannel",
    "build_notify_sms_channel",
]
