"""MOD-001: EXT-001 SMS/OTP delivery adapter (PHASE-2 T2, ticket #53).

One typed send operation behind a ``SmsAdapter`` protocol. The mock
implementation is the CI/local-dev default: it records the sent code per phone
for tests and never logs it. The provider implementation is the same interface
and is gated to staging/production by ``Settings`` (``__post_init__``), keeping
the real EXT-001 path out of dev/test.

EXT-001 call discipline (third-party-integration-standards §1/§3): timeout
<= 10 s, up to 3 retries (4 total attempts) with exponential + jitter,
server-side API key from settings only, and the OTP value never reaches a log
line (error-handling-observability: no OTPs, no tokens, no raw provider
payloads in logs). The circuit-breaker column of §1 is a later-phase concern,
not part of this ticket - the adapter honours timeout/retry here and logs a
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
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

import httpx
import pydantic
from pydantic import BaseModel, Field, field_validator

from app.config import (
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
            raise SmsDeliveryError(f"EXT-001 send rejected with HTTP {response.status_code}")
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
        raise SmsDeliveryError("EXT-001 returned a non-JSON response") from exc
    if not isinstance(payload, dict):
        raise SmsDeliveryError("EXT-001 returned an unexpected response payload")
    try:
        return SmsSendResult.model_validate(payload)
    except pydantic.ValidationError as exc:
        raise SmsDeliveryError(
            "EXT-001 returned an invalid response payload (expected request_id and status='queued')"
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
    """Resolve the EXT-001 adapter from config; mock is the CI/dev default."""
    provider = settings.sms_provider.strip().lower()
    if provider == "mock":
        return MockSmsAdapter()
    return SmsProviderAdapter(
        api_key=settings.sms_api_key,
        base_url=settings.sms_base_url,
        timeout_seconds=settings.sms_timeout_seconds,
        max_retries=settings.sms_max_retries,
    )
