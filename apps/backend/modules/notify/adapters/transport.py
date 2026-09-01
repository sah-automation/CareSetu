"""MOD-010: shared delivery-channel transport plumbing.

Both the WhatsApp (EXT-003) and SMS (EXT-001) channels used by the notify
module share two pieces of in-process infrastructure: the circuit breaker
that fast-fails sends during a provider outage (third-party-integration-
standards §1) and the background delivery queue that takes the provider call
out of the request path (§1: never in the user-critical path). This module
is the notify-side home of that shared plumbing so each channel adapter owns
only its provider, not a copy of the breaker and queue.

``DeliveryRequest`` is the one typed unit both channels carry - a recipient
phone and a body (ADR-0009's terminal-status message) plus the owning
notification row id - and ``ChannelAdapter.send`` is the single port every
channel implementation satisfies. ``on_delivery_failed`` is the callback the
queue invokes once a delivery has exhausted every retry, so the owning facade
can publish ``notification.failed`` (ADR-0009) outside the request path - the
notify-module analogue of MOD-001's ``otp.failed`` delivery emitter
(PHASE-2 REM T5, #81).
"""

from __future__ import annotations

import asyncio
import logging
import random
import secrets
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Literal, Protocol

import httpx
import pydantic
from pydantic import BaseModel

from modules.notify.domain.exceptions import NotificationDeliveryError

logger = logging.getLogger(__name__)


class DeliveryRequest(BaseModel):
    """The typed unit both WhatsApp and SMS channels deliver.

    ``notification_id`` names the owning row in ``notify.notifications`` so a
    ``notification.failed`` signal can correlate and, when appropriate, re-route
    to the fallback channel (ADR-0009). ``message`` is the terminal-status body;
    it is never a secret.
    """

    notification_id: int
    recipient_phone_e164: str
    message: str


class DeliveryResult(BaseModel):
    """The typed provider acknowledgement: ``{ request_id, status }``."""

    request_id: str
    status: Literal["queued"]


class ChannelAdapter(Protocol):
    """Port every notify channel implementation satisfies - one typed send."""

    async def send(self, request: DeliveryRequest) -> DeliveryResult: ...


class MockChannel:
    """CI/dev implementation: records sent messages for tests, never logs them.

    Shared by every channel adapter's mock variant.  ``request_id_prefix``
    is the only channel-specific bit (e.g. ``"mock-wa-"`` vs ``"mock-sms-"``).
    """

    def __init__(self, request_id_prefix: str = "mock-") -> None:
        self._request_id_prefix = request_id_prefix
        self._sent: dict[str, list[DeliveryRequest]] = {}

    async def send(self, request: DeliveryRequest) -> DeliveryResult:
        self._sent.setdefault(request.recipient_phone_e164, []).append(request)
        return DeliveryResult(
            request_id=f"{self._request_id_prefix}{secrets.token_hex(8)}",
            status="queued",
        )

    def sent_count(self, phone_e164: str) -> int:
        """How many sends have been recorded for ``phone_e164``."""
        return len(self._sent.get(phone_e164, []))

    def last_message(self, phone_e164: str) -> str | None:
        """The body of the most recent send to ``phone_e164``, or None."""
        sent = self._sent.get(phone_e164)
        if sent is None:
            return None
        return sent[-1].message


def _parse_provider_response(response: httpx.Response, *, integration_label: str) -> DeliveryResult:
    """Parse a generic ``{ request_id, status }`` provider acknowledgement.

    Shared by every HTTP provider channel; ``integration_label`` is the only
    channel-specific bit (e.g. ``"EXT-003 WhatsApp"`` vs ``"EXT-001 SMS"``)
    used in error messages.
    """
    try:
        payload = response.json()
    except ValueError as exc:
        raise NotificationDeliveryError(
            f"{integration_label} returned a non-JSON response",
            retries_exhausted=False,
        ) from exc
    if not isinstance(payload, dict):
        raise NotificationDeliveryError(
            f"{integration_label} returned an unexpected response payload",
            retries_exhausted=False,
        )
    try:
        return DeliveryResult.model_validate(payload)
    except pydantic.ValidationError as exc:
        raise NotificationDeliveryError(
            f"{integration_label} returned an invalid response payload "
            "(expected request_id and status='queued')",
            retries_exhausted=False,
        ) from exc


class HttpProviderChannel:
    """Shared HTTP provider implementation with retry and backoff.

    ``integration_label`` (e.g. ``"EXT-003 WhatsApp"``) is used in all log
    and error messages; the remaining constructor args are pure config.
    ``sleep`` is injectable so tests can exercise the retry loop without real
    waits.  The API key is passed by the caller from ``Settings`` - never read
    from code or logs.
    """

    def __init__(
        self,
        *,
        integration_label: str,
        send_path: str,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        max_retries: int,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._integration_label = integration_label
        self._send_path = send_path
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
                    f"{self._base_url}{self._send_path}",
                    json=payload,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                if attempt == self._max_retries:
                    logger.error(
                        "%s send failed after %d attempts (network error) for phone %s",
                        self._integration_label,
                        self._max_retries + 1,
                        mask_phone(request.recipient_phone_e164),
                    )
                    raise NotificationDeliveryError(
                        f"{self._integration_label} send failed after "
                        f"{self._max_retries + 1} attempts (network error)"
                    ) from exc
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last_status = response.status_code
                continue
            if response.is_success:
                return _parse_provider_response(response, integration_label=self._integration_label)
            logger.warning(
                "%s send rejected with HTTP %d for phone %s",
                self._integration_label,
                response.status_code,
                mask_phone(request.recipient_phone_e164),
            )
            raise NotificationDeliveryError(
                f"{self._integration_label} send rejected with HTTP {response.status_code}",
                retries_exhausted=False,
            )
        logger.error(
            "%s send failed after %d attempts (last HTTP %d) for phone %s",
            self._integration_label,
            self._max_retries + 1,
            last_status,
            mask_phone(request.recipient_phone_e164),
        )
        raise NotificationDeliveryError(
            f"{self._integration_label} send failed after "
            f"{self._max_retries + 1} attempts (last HTTP {last_status})"
        )


class CircuitBreakerState(StrEnum):
    """The three circuit-breaker states (third-party-integration-standards §1)."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """In-process state machine gating a provider send during an outage.

    Closed -> open after ``threshold`` consecutive outage failures; while open,
    ``allow_request`` fast-fails every send until ``cooldown_seconds`` elapses,
    then a half-open probe decides recovery: success closes the breaker, failure
    opens it again. The state machine owns no IO - ``allow_request`` gates a
    send and ``record_success``/``record_failure`` feed it outcomes. The clock
    is injectable so tests can drive the cooldown without sleeping; breaker
    state resets on process restart. Only genuine outages reach
    ``record_failure`` - the calling adapter gates on
    ``NotificationDeliveryError(retries_exhausted=True)``, so a 4xx contract
    rejection is never counted here.
    """

    def __init__(
        self,
        *,
        integration: str,
        threshold: int,
        cooldown_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._integration = integration
        self._threshold = threshold
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._state = CircuitBreakerState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> CircuitBreakerState:
        """The current breaker state (closed/open/half_open)."""
        return self._state

    def allow_request(self) -> bool:
        """Whether a send may proceed right now.

        While open, the first call past the cooldown transitions to half-open
        and lets the probe through; earlier calls are refused without touching
        the wrapped adapter.
        """
        if self._state is CircuitBreakerState.OPEN:
            if self._opened_at is not None and (
                self._clock() - self._opened_at >= self._cooldown_seconds
            ):
                self._state = CircuitBreakerState.HALF_OPEN
                return True
            return False
        return True

    def record_success(self) -> None:
        """Record a successful send; a half-open probe success closes the breaker."""
        if self._state is CircuitBreakerState.HALF_OPEN:
            logger.info(
                "%s circuit breaker recovered; the provider accepts sends again",
                self._integration,
            )
            self._state = CircuitBreakerState.CLOSED
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        """Record an outage failure; enough consecutive failures trip the breaker."""
        if self._state is CircuitBreakerState.HALF_OPEN:
            self._state = CircuitBreakerState.OPEN
            self._opened_at = self._clock()
            self._consecutive_failures = 1
            logger.warning(
                "%s circuit breaker re-opened after a half-open probe failed",
                self._integration,
            )
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._threshold:
            self._state = CircuitBreakerState.OPEN
            self._opened_at = self._clock()
            logger.warning(
                "%s circuit breaker opened after %d consecutive outage failures",
                self._integration,
                self._consecutive_failures,
            )


class CircuitBreakerChannel:
    """Wraps a provider adapter: gates each send through the circuit breaker.

    The mocks are never wrapped - this class exists only on the real provider
    path, where an outage must fast-fail every send instead of hammering the
    provider with full retries (third-party-integration-standards §1). While
    the breaker is open, ``send`` raises ``NotificationDeliveryError``
    immediately without touching the wrapped adapter, and the failure flows
    through the queue's degradation path (warn + ``notification.failed``
    emission) exactly like any retry-exhausted delivery. The half-open
    recovery probe is single-flight: a send racing an in-flight probe is
    refused the same way, so one slow probe cannot become a burst of
    concurrent provider calls.
    """

    def __init__(self, adapter: ChannelAdapter, breaker: CircuitBreaker) -> None:
        self._adapter = adapter
        self._breaker = breaker
        self._probe_in_flight = False

    async def send(self, request: DeliveryRequest) -> DeliveryResult:
        if not self._breaker.allow_request():
            raise NotificationDeliveryError(
                f"{self._breaker._integration} circuit breaker is open; "
                "send refused without calling the provider"
            )
        is_probe = self._breaker.state is CircuitBreakerState.HALF_OPEN
        if is_probe:
            if self._probe_in_flight:
                raise NotificationDeliveryError(
                    f"{self._breaker._integration} circuit breaker is half-open; "
                    "a recovery probe is already in flight"
                )
            self._probe_in_flight = True
        try:
            result = await self._adapter.send(request)
        except NotificationDeliveryError as exc:
            if exc.retries_exhausted:
                self._breaker.record_failure()
            raise
        finally:
            if is_probe:
                self._probe_in_flight = False
        self._breaker.record_success()
        return result


class NotificationDeliveryQueue:
    """In-process background delivery: the provider call leaves the request path.

    ADR-0009's transport engine enqueues each channel send here instead of
    awaiting the provider, so a slow or retrying provider never holds the
    caller's response (third-party-integration-standards §1). A background task
    delivers each enqueued request through the channel adapter as soon as the
    request yields to the event loop.

    Delivery is tracked in ``_pending`` until it finishes. ``flush`` awaits
    every pending delivery - the deterministic hook the unit/integration suites
    use to beat the async delivery race. A failed send is swallowed here: the
    provider adapter has already logged the failure, and the request has
    already answered - a background failure must never surface to a caller that
    received its flow state. ``on_delivery_failed`` (when given) is awaited once
    a delivery has exhausted every retry, so the owning facade can publish its
    ``notification.failed`` event (ADR-0009) outside the request path.
    """

    def __init__(
        self,
        adapter: ChannelAdapter,
        on_delivery_failed: Callable[[DeliveryRequest], Awaitable[None]] | None = None,
    ) -> None:
        self._adapter = adapter
        self._on_delivery_failed = on_delivery_failed
        self._pending: set[asyncio.Task[None]] = set()

    def enqueue(self, request: DeliveryRequest) -> None:
        """Schedule ``request`` for background delivery and return immediately."""
        task = asyncio.create_task(self._deliver(request))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    @property
    def pending_count(self) -> int:
        """How many deliveries have been scheduled but not yet finished."""
        return len(self._pending)

    async def flush(self) -> None:
        """Await every currently-pending delivery (a no-op when none are pending).

        A delivery enqueued after the flush started is not awaited; callers
        await the specific emission before flushing, so the flush covers the
        delivery that emission scheduled.
        """
        pending = tuple(self._pending)
        if pending:
            await asyncio.gather(*pending)

    async def _deliver(self, request: DeliveryRequest) -> None:
        try:
            await self._adapter.send(request)
        except NotificationDeliveryError as exc:
            logger.warning("background notification delivery failed")
            if exc.retries_exhausted and self._on_delivery_failed is not None:
                try:
                    await self._on_delivery_failed(request)
                except Exception:
                    # The failure signal must never crash the background task;
                    # log the emission failure so the loss is visible to
                    # operators.
                    logger.exception("failed to record notification delivery failure")
        except Exception:
            logger.exception("unexpected background notification delivery failure")


def mask_phone(phone_e164: str) -> str:
    """Redact a phone for logs: keep the ``+<cc>`` and the last two digits."""
    if len(phone_e164) <= 4:
        return "*" * len(phone_e164)
    return f"{phone_e164[:3]}...{phone_e164[-2:]}"


def mock_backoff_delay(
    attempt: int,
    base_seconds: float = 1.0,
    jitter_fraction: float = 0.25,
) -> float:
    """Exponential backoff with jitter for retry ``attempt`` (1-based)."""
    if attempt < 1:
        return 0.0
    exponential = base_seconds * (1 << (attempt - 1))
    jitter = random.uniform(0.0, exponential * jitter_fraction)  # nosec B311
    return exponential + jitter
