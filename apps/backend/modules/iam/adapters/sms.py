"""MOD-001: EXT-001 SMS/OTP delivery adapter (PHASE-2 T2, ticket #53).

One typed send operation behind a ``SmsAdapter`` protocol. The mock
implementation is the CI/local-dev default: it records the sent code per phone
for tests and never logs it. The provider implementation is the same interface
and is gated to staging/production by ``Settings`` (``__post_init__``), keeping
the real EXT-001 path out of dev/test.

EXT-001 call discipline (third-party-integration-standards §1/§3): timeout
<= 10 s, up to 3 retries (4 total attempts) with exponential + jitter, an
in-process circuit breaker (``CircuitBreaker``) that fast-fails every send
while a provider outage persists and probes recovery after a cooldown,
server-side API key from settings only, and the OTP value never reaches a log
line (error-handling-observability: no OTPs, no tokens, no raw provider
payloads in logs). Only genuine outage failures (network/timeout/5xx/429,
``SmsDeliveryError(retries_exhausted=True)``) trip the breaker - a 4xx
contract rejection never does. The provider adapter logs a
``patient.auth_failed`` marker on persistent failure so operators can alert.
The marker is the dot-notation event name (registry §4.2), not an event
envelope itself; if an external alert rule greps logs on the legacy name,
update it in the same change as renaming the marker.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
import secrets
import time
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Literal, Protocol

import httpx
import pydantic
from pydantic import BaseModel, Field, field_validator

from app.config import (
    DEFAULT_SMS_CIRCUIT_BREAKER_COOLDOWN_SECONDS,
    DEFAULT_SMS_CIRCUIT_BREAKER_THRESHOLD,
    DEFAULT_SMS_MAX_RETRIES,
    DEFAULT_SMS_TIMEOUT_SECONDS,
    Settings,
)
from modules.iam.domain.exceptions import SmsDeliveryError

logger = logging.getLogger(__name__)

_PHONE_E164_PATTERN = re.compile(r"^\+[0-9]{8,15}$")
_SEND_PATH = "/v1/send"


class SmsTemplateParams(BaseModel):
    """``params`` block of the EXT-001 request payload."""

    otp: str
    ttl_min: int = Field(default=5, ge=1, le=60)


class SmsSendRequest(BaseModel):
    """Typed EXT-001 request: ``{ phone_e164, template, params }``."""

    phone_e164: str
    template: str = "caresetu_otp"
    params: SmsTemplateParams

    @field_validator("phone_e164")
    @classmethod
    def _validate_phone_e164(cls, value: str) -> str:
        if _PHONE_E164_PATTERN.fullmatch(value) is None:
            raise ValueError("phone_e164 must be an E.164 number like +919000000000")
        return value


class SmsSendResult(BaseModel):
    """Typed EXT-001 response: ``{ request_id, status }``."""

    request_id: str
    status: Literal["queued"]


class SmsAdapter(Protocol):
    """Port every EXT-001 implementation satisfies - one typed send operation."""

    async def send(self, request: SmsSendRequest) -> SmsSendResult: ...


class MockSmsAdapter:
    """CI/dev implementation: records sent codes for tests, never logs them.

    ``last_sent_code`` is the read surface T3/T4/T5 and the E2E suite use to
    grab the OTP a given phone was sent (handoff note, ticket #53).
    """

    def __init__(self) -> None:
        self._sent: dict[str, list[SmsSendRequest]] = {}

    async def send(self, request: SmsSendRequest) -> SmsSendResult:
        self._sent.setdefault(request.phone_e164, []).append(request)
        return SmsSendResult(request_id=f"mock-{secrets.token_hex(8)}", status="queued")

    def last_sent_code(self, phone_e164: str) -> str | None:
        """The OTP of the most recent send to ``phone_e164``, or None."""
        sent = self._sent.get(phone_e164)
        if sent is None:
            return None
        return sent[-1].params.otp

    def sent_count(self, phone_e164: str) -> int:
        """How many sends have been recorded for ``phone_e164``."""
        return len(self._sent.get(phone_e164, []))


class SmsDeliveryQueue:
    """In-process background delivery: the EXT-001 send leaves the request path.

    PHASE-2 REM T4 (ticket #86): MOD-001 issues the challenge and writes
    ``otp.sent`` in one transaction, then ``enqueue``s the send here instead of
    awaiting the provider, so a slow or retrying provider never holds the
    patient's HTTP response (third-party-integration-standards §1: never in the
    user-critical path). A background task delivers each enqueued request
    through the ``SmsAdapter`` as soon as the request yields to the event loop.

    Delivery is tracked in ``_pending`` until it finishes. ``flush`` awaits
    every pending delivery - the deterministic hook the unit/integration suites
    and the dev/test OTP read-back route use to beat the async delivery race.
    A failed send is swallowed here: the provider adapter has already logged the
    ``patient.auth_failed`` marker with the redacted phone, and the request has
    already answered - a background failure must never surface to a caller that
    received its flow state. ``on_delivery_failed`` (when given) is awaited once
    a delivery has exhausted every retry, so the owning module can publish its
    delivery-failure event (PHASE-2 REM T5, #81) outside the request path.
    """

    def __init__(
        self,
        adapter: SmsAdapter,
        on_delivery_failed: Callable[[SmsSendRequest], Awaitable[None]] | None = None,
    ) -> None:
        self._adapter = adapter
        self._on_delivery_failed = on_delivery_failed
        self._pending: set[asyncio.Task[None]] = set()

    def enqueue(self, request: SmsSendRequest) -> None:
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
        await the specific issuance (register/resend returned) before flushing,
        so the flush covers the delivery that issuance scheduled.
        """
        pending = tuple(self._pending)
        if pending:
            await asyncio.gather(*pending)

    async def _deliver(self, request: SmsSendRequest) -> None:
        try:
            await self._adapter.send(request)
        except SmsDeliveryError as exc:
            # The provider adapter logged ``patient.auth_failed`` at error on
            # persistent failure; the request has already answered, so swallow
            # it here. Warn because the send degraded (observability §1:
            # degradations at warning), even for adapters that log no marker.
            logger.warning(
                "background SMS delivery failed for phone %s",
                mask_phone(request.phone_e164),
            )
            if exc.retries_exhausted and self._on_delivery_failed is not None:
                try:
                    await self._on_delivery_failed(request)
                except Exception:
                    # The delivery-failure event must never crash the
                    # background task the way the send never did; log the
                    # emission failure so audit loss is visible to operators.
                    logger.exception(
                        "failed to record delivery failure for phone %s",
                        mask_phone(request.phone_e164),
                    )
        except Exception:
            logger.exception(
                "unexpected background SMS delivery failure for phone %s",
                mask_phone(request.phone_e164),
            )


class CircuitBreakerState(StrEnum):
    """The three circuit-breaker states (third-party-integration-standards §1)."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """In-process state machine gating EXT-001 sends during a provider outage.

    Closed -> open after ``threshold`` consecutive outage failures; while open,
    ``allow_request`` fast-fails every send until ``cooldown_seconds`` elapses,
    then a half-open probe decides recovery: success closes the breaker, failure
    opens it again. The state machine owns no IO - ``allow_request`` gates a
    send and ``record_success``/``record_failure`` feed it outcomes. The clock
    is injectable so tests can drive the cooldown without sleeping; breaker
    state resets on process restart, the same in-process posture as the
    idempotency store and rate limiter (handoff note, ticket #104). Only
    genuine outages reach ``record_failure`` - the calling adapter gates on
    ``SmsDeliveryError(retries_exhausted=True)``, so a 4xx contract rejection
    is never counted here.
    """

    def __init__(
        self,
        *,
        threshold: int = DEFAULT_SMS_CIRCUIT_BREAKER_THRESHOLD,
        cooldown_seconds: float = DEFAULT_SMS_CIRCUIT_BREAKER_COOLDOWN_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
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
            logger.info("EXT-001 circuit breaker recovered; the provider accepts sends again")
            self._state = CircuitBreakerState.CLOSED
        self._consecutive_failures = 0

    def record_failure(self) -> None:
        """Record an outage failure; enough consecutive failures trip the breaker."""
        if self._state is CircuitBreakerState.HALF_OPEN:
            self._state = CircuitBreakerState.OPEN
            self._opened_at = self._clock()
            self._consecutive_failures = 1
            logger.warning("EXT-001 circuit breaker re-opened after a half-open probe failed")
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._threshold:
            self._state = CircuitBreakerState.OPEN
            self._opened_at = self._clock()
            logger.warning(
                "EXT-001 circuit breaker opened after %d consecutive outage failures",
                self._consecutive_failures,
            )


class CircuitBreakerSmsAdapter:
    """Wraps the provider adapter: gates each send through the circuit breaker.

    The mock is never wrapped - this class exists only on the real EXT-001
    path, where an outage must fast-fail every send instead of hammering the
    provider with full retries (third-party-integration-standards §1). While
    the breaker is open, ``send`` raises ``SmsDeliveryError`` immediately
    without touching the wrapped adapter, and the failure flows through the
    queue's degradation path (warn + ``on_delivery_failed`` audit event)
    exactly like any retry-exhausted delivery. The half-open recovery probe is
    single-flight: a send racing an in-flight probe is refused the same way,
    so one slow probe cannot become a burst of concurrent provider calls.
    """

    def __init__(self, adapter: SmsAdapter, breaker: CircuitBreaker) -> None:
        self._adapter = adapter
        self._breaker = breaker
        self._probe_in_flight = False

    async def send(self, request: SmsSendRequest) -> SmsSendResult:
        if not self._breaker.allow_request():
            raise SmsDeliveryError(
                "EXT-001 circuit breaker is open; send refused without calling the provider"
            )
        is_probe = self._breaker.state is CircuitBreakerState.HALF_OPEN
        if is_probe:
            if self._probe_in_flight:
                raise SmsDeliveryError(
                    "EXT-001 circuit breaker is half-open; a recovery probe is already in flight"
                )
            self._probe_in_flight = True
        try:
            result = await self._adapter.send(request)
        except SmsDeliveryError as exc:
            if exc.retries_exhausted:
                self._breaker.record_failure()
            raise
        finally:
            if is_probe:
                self._probe_in_flight = False
        self._breaker.record_success()
        return result


class SmsProviderAdapter:
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

    async def send(self, request: SmsSendRequest) -> SmsSendResult:
        payload = request.model_dump(mode="json")
        headers = {"Authorization": f"Bearer {self._api_key}"}
        last_status = 0
        for attempt in range(self._max_retries + 1):
            if attempt > 0:
                await self._sleep(backoff_delay(attempt))
            try:
                response = await self._client.post(
                    f"{self._base_url}{_SEND_PATH}",
                    json=payload,
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                if attempt == self._max_retries:
                    logger.error(
                        "patient.auth_failed: EXT-001 send failed after %d attempts "
                        "(network error) for phone %s",
                        self._max_retries + 1,
                        mask_phone(request.phone_e164),
                    )
                    raise SmsDeliveryError(
                        "EXT-001 send failed after "
                        f"{self._max_retries + 1} attempts (network error)"
                    ) from exc
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last_status = response.status_code
                continue
            if response.is_success:
                return _parse_response(response)
            logger.warning(
                "EXT-001 send rejected with HTTP %d for phone %s",
                response.status_code,
                mask_phone(request.phone_e164),
            )
            raise SmsDeliveryError(
                f"EXT-001 send rejected with HTTP {response.status_code}",
                retries_exhausted=False,
            )
        logger.error(
            "patient.auth_failed: EXT-001 send failed after %d attempts "
            "(last HTTP %d) for phone %s",
            self._max_retries + 1,
            last_status,
            mask_phone(request.phone_e164),
        )
        raise SmsDeliveryError(
            f"EXT-001 send failed after {self._max_retries + 1} attempts (last HTTP {last_status})"
        )


def _parse_response(response: httpx.Response) -> SmsSendResult:
    try:
        payload = response.json()
    except ValueError as exc:
        raise SmsDeliveryError(
            "EXT-001 returned a non-JSON response", retries_exhausted=False
        ) from exc
    if not isinstance(payload, dict):
        raise SmsDeliveryError(
            "EXT-001 returned an unexpected response payload", retries_exhausted=False
        )
    try:
        return SmsSendResult.model_validate(payload)
    except pydantic.ValidationError as exc:
        raise SmsDeliveryError(
            "EXT-001 returned an invalid response payload "
            "(expected request_id and status='queued')",
            retries_exhausted=False,
        ) from exc


def backoff_delay(
    attempt: int,
    base_seconds: float = 1.0,
    jitter_fraction: float = 0.25,
) -> float:
    """Exponential backoff with jitter for retry ``attempt`` (1-based).

    Jitter spreads retries across instances to avoid thundering herds; it is
    not a security source, so the pseudo-random uniform is bandit-safe (B311).
    """
    if attempt < 1:
        return 0.0
    exponential = base_seconds * (1 << (attempt - 1))
    jitter = random.uniform(0.0, exponential * jitter_fraction)  # nosec B311
    return exponential + jitter


def mask_phone(phone_e164: str) -> str:
    """Redact a phone for logs: keep the ``+<cc>`` and the last two digits."""
    if len(phone_e164) <= 4:
        return "*" * len(phone_e164)
    return f"{phone_e164[:3]}...{phone_e164[-2:]}"


def build_sms_adapter(settings: Settings) -> SmsAdapter:
    """Resolve the EXT-001 adapter from config; mock is the CI/dev default.

    Only the provider branch is wrapped in the circuit breaker - the mock stays
    unwrapped so dev/E2E sends are never fast-failed (acceptance, ticket #104).
    """
    provider = settings.sms_provider.strip().lower()
    if provider == "mock":
        return MockSmsAdapter()
    return CircuitBreakerSmsAdapter(
        SmsProviderAdapter(
            api_key=settings.sms_api_key,
            base_url=settings.sms_base_url,
            timeout_seconds=settings.sms_timeout_seconds,
            max_retries=settings.sms_max_retries,
        ),
        CircuitBreaker(
            threshold=settings.sms_circuit_breaker_threshold,
            cooldown_seconds=settings.sms_circuit_breaker_cooldown_seconds,
        ),
    )
