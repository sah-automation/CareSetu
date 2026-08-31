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
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Awaitable, Callable

import httpx
import pydantic

from app.config import (
    DEFAULT_SMS_MAX_RETRIES,
    DEFAULT_SMS_TIMEOUT_SECONDS,
    Settings,
)
from modules.notify.adapters.transport import (
    ChannelAdapter,
    CircuitBreaker,
    CircuitBreakerChannel,
    DeliveryRequest,
    DeliveryResult,
    mask_phone,
    mock_backoff_delay,
)
from modules.notify.domain.exceptions import NotificationDeliveryError

logger = logging.getLogger(__name__)

_SEND_PATH = "/v1/send"


class MockNotifySmsChannel:
    """CI/dev implementation: records sent messages for tests, never logs them."""

    def __init__(self) -> None:
        self._sent: dict[str, list[DeliveryRequest]] = {}

    async def send(self, request: DeliveryRequest) -> DeliveryResult:
        self._sent.setdefault(request.recipient_phone_e164, []).append(request)
        return DeliveryResult(request_id=f"mock-sms-{secrets.token_hex(8)}", status="queued")

    def sent_count(self, phone_e164: str) -> int:
        """How many sends have been recorded for ``phone_e164``."""
        return len(self._sent.get(phone_e164, []))

    def last_message(self, phone_e164: str) -> str | None:
        """The body of the most recent send to ``phone_e164``, or None."""
        sent = self._sent.get(phone_e164)
        if sent is None:
            return None
        return sent[-1].message


class NotifySmsProviderChannel:
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
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._sleep = sleep
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def send(self, request: DeliveryRequest) -> DeliveryResult:
        payload = {
            "recipient_phone_e164": request.recipient_phone_e164,
            "message": request.message,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_status = 0
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                await self._sleep(mock_backoff_delay(attempt))
            try:
                response = await self._client.post(
                    f"{self._base_url}{_SEND_PATH}",
                    json=payload,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                if attempt == self._max_retries:
                    logger.error(
                        "EXT-001 SMS send failed after %d attempts (network error) for phone %s",
                        self._max_retries + 1,
                        mask_phone(request.recipient_phone_e164),
                    )
                    raise NotificationDeliveryError(
                        "EXT-001 SMS send failed after "
                        f"{self._max_retries + 1} attempts (network error)"
                    ) from exc
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last_status = response.status_code
                continue
            if response.is_success:
                return _parse_sms_response(response)
            logger.warning(
                "EXT-001 SMS send rejected with HTTP %d for phone %s",
                response.status_code,
                mask_phone(request.recipient_phone_e164),
            )
            raise NotificationDeliveryError(
                f"EXT-001 SMS send rejected with HTTP {response.status_code}",
                retries_exhausted=False,
            )
        logger.error(
            "EXT-001 SMS send failed after %d attempts (last HTTP %d) for phone %s",
            self._max_retries + 1,
            last_status,
            mask_phone(request.recipient_phone_e164),
        )
        raise NotificationDeliveryError(
            "EXT-001 SMS send failed after "
            f"{self._max_retries + 1} attempts (last HTTP {last_status})"
        )


def _parse_sms_response(response: httpx.Response) -> DeliveryResult:
    try:
        payload = response.json()
    except ValueError as exc:
        raise NotificationDeliveryError(
            "EXT-001 SMS returned a non-JSON response", retries_exhausted=False
        ) from exc
    if not isinstance(payload, dict):
        raise NotificationDeliveryError(
            "EXT-001 SMS returned an unexpected response payload",
            retries_exhausted=False,
        )
    try:
        return DeliveryResult.model_validate(payload)
    except pydantic.ValidationError as exc:
        raise NotificationDeliveryError(
            "EXT-001 SMS returned an invalid response payload "
            "(expected request_id and status='queued')",
            retries_exhausted=False,
        ) from exc


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
