"""MOD-005: AI job completion webhook adapter (ARCH-P3 #853).

Optional outbound webhook announcing AI job completion/failure. Completely
inert unless a URL is configured. Reuses the EXT-002 retry/backoff policy
via ``post_with_backoff``; delivery failures are retried by that helper and
never propagate to the AI pipeline.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from bus.envelope import Envelope
from bus.events import EVENT_AI_JOB_COMPLETED
from modules.intake.adapters.ai_gateway import Ext002CallError, post_with_backoff
from modules.intake.domain.events import AiJobCompletedPayload, AiJobFailedPayload  # noqa: F401
from modules.notify.adapters.transport import CircuitBreaker

logger = logging.getLogger(__name__)

#: Header carrying the HMAC-SHA256 signature (hex) of the raw request body.
SIGNATURE_HEADER = "X-Webhook-Signature"
SIGNATURE_HEADER_ALIASES = (
    "X-Webhook-Signature",
    "X-Signature",
    "X-Hub-Signature-256",
)
#: Header carrying the unix epoch seconds the sender stamped; receivers
#: reject stale/replayed callbacks.
TIMESTAMP_HEADER = "X-Webhook-Timestamp"
TIMESTAMP_HEADER_ALIASES = ("X-Webhook-Timestamp", "X-Timestamp")

ALLOWED_PAYLOAD_FIELDS = frozenset(
    {
        "event_id",
        "event_type",
        "ai_job_id",
        "intake_id",
        "task_type",
        "status",
        "provider",
        "model",
        "input_tokens",
        "output_tokens",
        "cost_paise",
        "duration_ms",
        "trace_id",
    }
)


def _payload_value(payload: Any, name: str, default: Any = None) -> Any:
    if isinstance(payload, dict):
        return payload.get(name, default)
    try:
        return getattr(payload, name, default)
    except Exception:
        return default


def build_ai_job_webhook_payload(envelope: Envelope[Any]) -> dict[str, Any]:
    """Project the event onto the PHI-free webhook payload."""
    payload = envelope.payload
    event_type = envelope.event_type
    status = "completed" if event_type == EVENT_AI_JOB_COMPLETED else "failed"
    if event_type == EVENT_AI_JOB_COMPLETED:
        input_tokens = _payload_value(payload, "input_tokens", 0)
        output_tokens = _payload_value(payload, "output_tokens", 0)
        cost_paise = _payload_value(payload, "cost_paise", 0)
        duration_ms = _payload_value(payload, "duration_ms", 0)
    else:
        input_tokens = 0
        output_tokens = 0
        cost_paise = 0
        duration_ms = 0
    return {
        "event_id": str(envelope.event_id),
        "event_type": event_type,
        "ai_job_id": _payload_value(payload, "ai_job_id"),
        "intake_id": _payload_value(payload, "intake_id"),
        "task_type": _payload_value(payload, "task_type"),
        "status": status,
        "provider": _payload_value(payload, "provider", ""),
        "model": _payload_value(payload, "model", ""),
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "cost_paise": int(cost_paise or 0),
        "duration_ms": int(duration_ms or 0),
        "trace_id": _payload_value(payload, "trace_id", None),
    }


class AiJobWebhookAdapter:
    """Outbound adapter delivering AI job completion events via HTTP."""

    SIGNATURE_HEADER = SIGNATURE_HEADER
    TIMESTAMP_HEADER = TIMESTAMP_HEADER
    ALLOWED_PAYLOAD_FIELDS = ALLOWED_PAYLOAD_FIELDS

    def __init__(
        self,
        url: str | None = None,
        secret: str | None = None,
        *,
        webhook_url: str | None = None,
        signing_secret: str | None = None,
        webhook_secret: str | None = None,
        timeout_seconds: float | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        max_attempts: int | None = None,
        max_retries_override: int | None = None,
        client: httpx.AsyncClient | None = None,
        transport: httpx.MockTransport | httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        timestamp_factory: Callable[[], int] | None = None,
        settings: Any = None,
        **kwargs: Any,
    ) -> None:
        # Best-effort resolution from settings / kwargs so callers can pass
        # nothing and let the adapter pull from configuration.
        if url is None:
            url = kwargs.get("url")
        if webhook_url is not None:
            url = webhook_url
        if url is None:
            url = kwargs.get("webhook_url")
        if url is None and settings is not None:
            url = getattr(settings, "ai_webhook_url", None) or getattr(
                settings, "ai_job_webhook_url", None
            )
        if secret is None:
            secret = kwargs.get("secret")
        if signing_secret is not None:
            secret = signing_secret
        if webhook_secret is not None:
            secret = webhook_secret
        if secret is None:
            secret = kwargs.get("signing_secret") or kwargs.get("webhook_secret")
        if secret is None and settings is not None:
            secret = (
                getattr(settings, "ai_webhook_secret", None)
                or getattr(settings, "ai_webhook_signing_secret", None)
                or getattr(settings, "ai_job_webhook_secret", None)
                or getattr(settings, "ai_job_webhook_signing_secret", None)
            )
        if url is None:
            url = kwargs.get("webhook")
        self.url = (url or "").strip()
        self.secret = (secret or "").strip()
        if timeout_seconds is not None:
            self.timeout_seconds = float(timeout_seconds)
        elif timeout is not None:
            self.timeout_seconds = float(timeout)
        elif settings is not None:
            self.timeout_seconds = float(
                getattr(settings, "ai_webhook_timeout_seconds", 10.0) or 10.0
            )
        else:
            self.timeout_seconds = float(kwargs.get("timeout_seconds", 10.0) or 10.0)
        if max_attempts is not None:
            self.max_retries = max(0, int(max_attempts) - 1)
        elif max_retries is not None:
            self.max_retries = int(max_retries)
        elif max_retries_override is not None:
            self.max_retries = int(max_retries_override)
        elif settings is not None:
            attempts = getattr(settings, "ai_webhook_max_attempts", None)
            if attempts is not None:
                self.max_retries = max(0, int(attempts) - 1)
            else:
                self.max_retries = int(getattr(settings, "ai_webhook_max_retries", 3) or 3)
        else:
            self.max_retries = int(kwargs.get("max_retries", 3) or 3)
        self._sleep = sleep
        self._timestamp_factory = timestamp_factory or (lambda: int(time.time()))
        if client is not None:
            self._client = client
        elif transport is not None:
            self._client = httpx.AsyncClient(transport=transport, timeout=self.timeout_seconds)
        else:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
        self._owns_client = client is None
        if settings is not None:
            threshold = getattr(settings, "ai_circuit_breaker_threshold", 5)
            cooldown = getattr(settings, "ai_circuit_breaker_cooldown_seconds", 30.0)
        else:
            threshold = kwargs.get("circuit_breaker_threshold", 5)
            cooldown = kwargs.get("circuit_breaker_cooldown_seconds", 30.0)
        try:
            threshold_int = int(threshold)
        except (TypeError, ValueError):
            threshold_int = 5
        try:
            cooldown_float = float(cooldown)
        except (TypeError, ValueError):
            cooldown_float = 30.0
        self._breaker = CircuitBreaker(
            integration="ai_job_webhook",
            threshold=threshold_int if threshold_int > 0 else 5,
            cooldown_seconds=cooldown_float if cooldown_float > 0 else 30.0,
            enabled=True,
        )
    @property
    def webhook_url(self) -> str:  # compatibility alias
        return self.url

    @property
    def max_attempts(self) -> int:
        return self.max_retries + 1

    @property
    def timeout(self) -> float:
        return self.timeout_seconds

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _build_headers(self, body: bytes, timestamp: str) -> dict[str, str]:
        signature = hmac.new(self.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        headers: dict[str, str] = {
            SIGNATURE_HEADER: signature,
            TIMESTAMP_HEADER: timestamp,
            "Content-Type": "application/json",
        }
        for name in SIGNATURE_HEADER_ALIASES:
            headers[name] = signature
        for name in TIMESTAMP_HEADER_ALIASES:
            headers[name] = timestamp
        return headers

    async def send(self, envelope: Any, *, client: httpx.AsyncClient | None = None) -> Any:
        return await self.deliver(envelope, client=client)

    async def deliver(self, envelope: Any, *, client: httpx.AsyncClient | None = None) -> Any:
        payload = build_ai_job_webhook_payload(envelope)
        body_bytes = httpx.Request("POST", self.url, json=payload).content
        timestamp = str(self._timestamp_factory())
        headers = self._build_headers(body_bytes, timestamp)
        if not self._breaker.allow_request():
            raise Ext002CallError(
                "ai job webhook circuit breaker is open; delivery refused",
                retries_exhausted=True,
            )
        active_client = client or self._client
        try:
            result = await post_with_backoff(
                active_client,
                self.url,
                json_body=payload,
                headers=headers,
                max_retries=self.max_retries,
                sleep=self._sleep,
                label="ai_job_webhook",
            )
        except Ext002CallError as exc:
            if exc.retries_exhausted:
                self._breaker.record_failure()
            # Secret never appears in these messages (they only name provider/url).
            logger.warning("ai job webhook delivery failed for %s", envelope.event_id)
            raise
        self._breaker.record_success()
        return result

    async def handle(self, envelope: Any, *, client: httpx.AsyncClient | None = None) -> Any:
        return await self.deliver(envelope, client=client)

    async def __call__(self, envelope: Any, *, client: httpx.AsyncClient | None = None) -> Any:
        return await self.deliver(envelope, client=client)


def _candidate_settings(settings: Any = None) -> Any:
    if settings is not None:
        return settings
    try:
        from app.config import get_settings as _get

        return _get()
    except Exception:
        return None


def build_ai_job_webhook_adapter(
    settings: Any = None,
    *,
    url: str | None = None,
    secret: str | None = None,
    **kwargs: Any,
) -> AiJobWebhookAdapter:
    effective_settings = _candidate_settings(settings)
    if url is None and effective_settings is not None:
        url = getattr(effective_settings, "ai_webhook_url", "")
    if secret is None and effective_settings is not None:
        secret = getattr(effective_settings, "ai_webhook_secret", None) or getattr(
            effective_settings, "ai_webhook_signing_secret", None
        )
    extra: dict[str, Any] = {}
    if effective_settings is not None:
        extra.setdefault(
            "timeout_seconds", getattr(effective_settings, "ai_webhook_timeout_seconds", None)
        )
        extra.setdefault(
            "max_attempts", getattr(effective_settings, "ai_webhook_max_attempts", None)
        )
    extra.update(kwargs)
    return AiJobWebhookAdapter(url=url, secret=secret, settings=effective_settings, **extra)


# Backwards/alt naming aliases for tests and registration.
AiJobCompletionWebhookAdapter = AiJobWebhookAdapter
AiJobWebhook = AiJobWebhookAdapter
AiCompletionWebhookAdapter = AiJobWebhookAdapter
WebhookAdapter = AiJobWebhookAdapter


async def deliver_ai_job_webhook(envelope: Any, **kwargs: Any) -> Any:
    client = kwargs.pop("client", None)
    adapter = build_ai_job_webhook_adapter(**kwargs) if kwargs else None
    if adapter is None:
        return await AiJobWebhookAdapter().deliver(envelope, client=client)
    return await adapter.deliver(envelope, client=client)


async def send_ai_job_webhook(envelope: Any, **kwargs: Any) -> Any:
    return await deliver_ai_job_webhook(envelope, **kwargs)


async def handle_ai_job_webhook(envelope: Any, **kwargs: Any) -> Any:
    return await deliver_ai_job_webhook(envelope, **kwargs)


# Common simple aliases for a single-event handler entry point.
on_ai_job_completed = None
on_ai_job_failed = None

__all__ = [
    "ALLOWED_PAYLOAD_FIELDS",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "AiCompletionWebhookAdapter",
    "AiJobCompletionWebhookAdapter",
    "AiJobWebhook",
    "AiJobWebhookAdapter",
    "WebhookAdapter",
    "build_ai_job_webhook_adapter",
    "build_ai_job_webhook_payload",
    "deliver_ai_job_webhook",
    "handle_ai_job_webhook",
    "send_ai_job_webhook",
]
