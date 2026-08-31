"""T11 (#246): MOD-010 WhatsApp/SMS fallback channel engine.

Acceptance contract from the ticket: the notify facade exposes a send-with-
fallback primitive that routes WhatsApp (EXT-003) first, then SMS (EXT-001) on
delivery failure; delivery is non-blocking (background queued) matching the iam
SMS adapter pattern; a ``notification.failed`` signal on the WhatsApp channel
triggers the SMS fallback, and the SMS leg is terminal (no loop). Mirrors
``test_iam_sms_adapter.py``.
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from app.config import (
    DEFAULT_WHATSAPP_CIRCUIT_BREAKER_COOLDOWN_SECONDS,
    DEFAULT_WHATSAPP_CIRCUIT_BREAKER_THRESHOLD,
    DEFAULT_WHATSAPP_MAX_RETRIES,
    DEFAULT_WHATSAPP_PROVIDER,
    DEFAULT_WHATSAPP_TIMEOUT_SECONDS,
    Settings,
)
from modules.notify.adapters.sms import (
    MockNotifySmsChannel,
    NotifySmsProviderChannel,
    build_notify_sms_channel,
)
from modules.notify.adapters.transport import (
    CircuitBreaker,
    CircuitBreakerChannel,
    CircuitBreakerState,
    DeliveryRequest,
    DeliveryResult,
    NotificationDeliveryQueue,
)
from modules.notify.adapters.whatsapp import (
    MockWhatsAppChannel,
    WhatsAppProviderChannel,
    build_whatsapp_channel,
    mock_backoff_delay,
)
from modules.notify.domain.events import NotificationFailedPayload
from modules.notify.domain.exceptions import NotificationDeliveryError
from modules.notify.facade import NotifyFacade

_PHONE = "+919876543210"
_MESSAGE = "Your CareSetu partner account is now active."
_NOTIFICATION_ID = 7


def _request(
    notification_id: int = _NOTIFICATION_ID,
    phone: str = _PHONE,
    message: str = _MESSAGE,
) -> DeliveryRequest:
    return DeliveryRequest(
        notification_id=notification_id,
        recipient_phone_e164=phone,
        message=message,
    )


async def _noop_sleep(delay: float) -> None:
    pass


class _RecordingEmitter:
    """Records the ``notification.failed`` payloads the facade emits."""

    def __init__(self) -> None:
        self.emitted: list[NotificationFailedPayload] = []

    async def __call__(self, payload: NotificationFailedPayload) -> None:
        self.emitted.append(payload)


class _FailingChannel:
    """A channel whose send always fails (retries exhausted)."""

    def __init__(self, label: str = "delivery") -> None:
        self.label = label

    async def send(self, request: DeliveryRequest) -> DeliveryResult:
        raise NotificationDeliveryError(f"{self.label} unavailable")


class _RecordingCallback:
    def __init__(self) -> None:
        self.calls: list[DeliveryRequest] = []

    async def __call__(self, request: DeliveryRequest) -> None:
        self.calls.append(request)


# --- facade: send-with-fallback routes WhatsApp first, non-blocking -----------


async def test_send_with_fallback_routes_whatsapp_first() -> None:
    wa = MockWhatsAppChannel()
    sms = MockNotifySmsChannel()
    facade = NotifyFacade(wa, sms, wa_failed_emitter=_RecordingEmitter())

    await facade.send_with_fallback(_request())
    await facade.flush()

    assert wa.sent_count(_PHONE) == 1
    assert wa.last_message(_PHONE) == _MESSAGE
    # WhatsApp attempted first; SMS is not touched on the happy path.
    assert sms.sent_count(_PHONE) == 0


async def test_send_with_fallback_is_non_blocking() -> None:
    class _BlockingChannel:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.release = asyncio.Event()
            self.sent: list[DeliveryRequest] = []

        async def send(self, request: DeliveryRequest) -> DeliveryResult:
            self.sent.append(request)
            self.started.set()
            await self.release.wait()
            return DeliveryResult(request_id="slow", status="queued")

    wa = _BlockingChannel()
    sms = MockNotifySmsChannel()
    facade = NotifyFacade(wa, sms, wa_failed_emitter=_RecordingEmitter())

    await facade.send_with_fallback(_request())
    await wa.started.wait()

    # The call returned before delivery finished - non-blocking (standards §1).
    assert wa.sent == [_request()]
    wa.release.set()
    await facade.flush()


# --- delivery-failure emission: a WA failure emits notification.failed --------


async def test_wa_delivery_failure_emits_notification_failed() -> None:
    emitter = _RecordingEmitter()
    facade = NotifyFacade(_FailingChannel(), MockNotifySmsChannel(), wa_failed_emitter=emitter)

    await facade.send_with_fallback(_request())
    await facade.flush()

    assert len(emitter.emitted) == 1
    signal = emitter.emitted[0]
    assert signal.notification_id == _NOTIFICATION_ID
    assert signal.channel == "wa"
    assert signal.recipient_phone_e164 == _PHONE
    assert signal.message == _MESSAGE


async def test_successful_wa_delivery_emits_no_failure_signal() -> None:
    emitter = _RecordingEmitter()
    facade = NotifyFacade(MockWhatsAppChannel(), MockNotifySmsChannel(), wa_failed_emitter=emitter)

    await facade.send_with_fallback(_request())
    await facade.flush()

    assert emitter.emitted == []


async def test_unexpected_failure_does_not_emit_failure_signal() -> None:
    class _BuggyChannel:
        async def send(self, request: DeliveryRequest) -> DeliveryResult:
            raise RuntimeError("provider bug")

    emitter = _RecordingEmitter()
    facade = NotifyFacade(_BuggyChannel(), MockNotifySmsChannel(), wa_failed_emitter=emitter)

    await facade.send_with_fallback(_request())
    await facade.flush()

    assert emitter.emitted == []
    assert facade.whatsapp_queue.pending_count == 0


# --- fallback: notification.failed (wa) re-routes to SMS -----------------------


async def test_wa_failure_enqueues_sms_fallback() -> None:
    wa = MockWhatsAppChannel()
    sms = MockNotifySmsChannel()
    emitter = _RecordingEmitter()
    facade = NotifyFacade(wa, sms, wa_failed_emitter=emitter)

    # Simulate the notification.failed handler reconstructing a WA failure.
    await facade.send_with_fallback(_request())
    # WhatsApp then fails -> signal -> handler re-routes to SMS.
    await facade.enqueue_sms_fallback(_request())
    await facade.flush()

    assert sms.sent_count(_PHONE) == 1
    assert sms.last_message(_PHONE) == _MESSAGE


async def test_sms_failure_is_terminal_and_does_not_re_enter_the_chain() -> None:
    # The SMS leg is the fallback's last hop (ADR-0009): the facade wires its
    # SMS queue with NO delivery-failed hook, so a failed SMS delivery is
    # swallowed - it must never emit ``notification.failed`` and loop.
    emitter = _RecordingEmitter()
    facade = NotifyFacade(MockWhatsAppChannel(), _FailingChannel("SMS"), wa_failed_emitter=emitter)

    await facade.enqueue_sms_fallback(_request())
    await facade.flush()

    assert facade.sms_queue.pending_count == 0
    assert emitter.emitted == []


# --- mock implementations ------------------------------------------------------


async def test_mock_whatsapp_records_and_never_logs(caplog: pytest.LogCaptureFixture) -> None:
    wa = MockWhatsAppChannel()
    caplog.set_level(logging.DEBUG)

    await wa.send(_request())

    assert wa.sent_count(_PHONE) == 1
    assert wa.last_message(_PHONE) == _MESSAGE
    assert _MESSAGE not in caplog.text
    assert _PHONE not in caplog.text


async def test_mock_sms_records_and_returns_typed_result() -> None:
    sms = MockNotifySmsChannel()

    result = await sms.send(_request())

    assert isinstance(result, DeliveryResult)
    assert result.status == "queued"
    assert result.request_id.startswith("mock-sms-")
    assert sms.sent_count(_PHONE) == 1


# --- config gating ------------------------------------------------------------


def test_settings_default_to_whatsapp_mock() -> None:
    settings = Settings()

    assert settings.whatsapp_provider == DEFAULT_WHATSAPP_PROVIDER
    assert settings.whatsapp_timeout_seconds == DEFAULT_WHATSAPP_TIMEOUT_SECONDS
    assert settings.whatsapp_max_retries == DEFAULT_WHATSAPP_MAX_RETRIES
    assert settings.whatsapp_api_key == ""
    assert settings.whatsapp_base_url == ""
    assert settings.whatsapp_circuit_breaker_threshold == (
        DEFAULT_WHATSAPP_CIRCUIT_BREAKER_THRESHOLD
    )
    assert settings.whatsapp_circuit_breaker_cooldown_seconds == (
        DEFAULT_WHATSAPP_CIRCUIT_BREAKER_COOLDOWN_SECONDS
    )


@pytest.mark.parametrize("environment", ["dev", "test"])
def test_settings_refuse_whatsapp_provider_in_dev_test(environment: str) -> None:
    with pytest.raises(ValueError, match=r"WHATSAPP_PROVIDER|whatsapp_provider"):
        Settings(
            whatsapp_provider="provider",
            whatsapp_api_key="k",
            whatsapp_base_url="https://wa.test",
            app_environment=environment,
        )


def test_settings_whatsapp_provider_requires_api_key() -> None:
    with pytest.raises(ValueError, match="WHATSAPP_API_KEY"):
        Settings(
            whatsapp_provider="provider",
            whatsapp_base_url="https://wa.test",
            app_environment="production",
        )


def test_settings_whatsapp_provider_requires_base_url() -> None:
    with pytest.raises(ValueError, match="WHATSAPP_BASE_URL"):
        Settings(
            whatsapp_provider="provider",
            whatsapp_api_key="k",
            app_environment="production",
        )


def test_settings_accept_whatsapp_provider_in_staging() -> None:
    settings = Settings(
        whatsapp_provider="provider",
        whatsapp_api_key="k",
        whatsapp_base_url="https://wa.test",
        app_environment="staging",
    )

    assert settings.whatsapp_provider == "provider"


def test_settings_reject_unknown_whatsapp_provider() -> None:
    with pytest.raises(ValueError, match="whatsapp_provider"):
        Settings(whatsapp_provider="carrier-pigeon")


@pytest.mark.parametrize("timeout_seconds", [0, -1, 10.5, 30])
def test_settings_refuse_whatsapp_timeout_outside_ext003_discipline(
    timeout_seconds: float,
) -> None:
    with pytest.raises(ValueError, match="whatsapp_timeout_seconds"):
        Settings(whatsapp_timeout_seconds=timeout_seconds)


def test_settings_accept_whatsapp_timeout_boundary_of_ten_seconds() -> None:
    settings = Settings(whatsapp_timeout_seconds=10.0)
    assert settings.whatsapp_timeout_seconds == 10.0


@pytest.mark.parametrize("threshold", [0, -1])
def test_settings_refuse_non_positive_whatsapp_breaker_threshold(threshold: int) -> None:
    with pytest.raises(ValueError, match="whatsapp_circuit_breaker_threshold"):
        Settings(whatsapp_circuit_breaker_threshold=threshold)


@pytest.mark.parametrize("cooldown_seconds", [0.0, -2.0])
def test_settings_refuse_non_positive_whatsapp_breaker_cooldown(cooldown_seconds: float) -> None:
    with pytest.raises(ValueError, match="whatsapp_circuit_breaker_cooldown_seconds"):
        Settings(whatsapp_circuit_breaker_cooldown_seconds=cooldown_seconds)


def test_build_channels_default_to_mock() -> None:
    wa = build_whatsapp_channel(Settings())
    sms = build_notify_sms_channel(Settings())

    assert isinstance(wa, MockWhatsAppChannel)
    assert isinstance(sms, MockNotifySmsChannel)


def test_build_whatsapp_channel_wraps_provider_in_circuit_breaker() -> None:
    channel = build_whatsapp_channel(
        Settings(
            whatsapp_provider="provider",
            whatsapp_api_key="k",
            whatsapp_base_url="https://wa.test",
            app_environment="staging",
        )
    )

    assert isinstance(channel, CircuitBreakerChannel)


# --- provider adapter retry/discipline ----------------------------------------


async def test_wa_provider_send_post_and_parse() -> None:
    import json

    import httpx

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"request_id": "wa-1", "status": "queued"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    channel = WhatsAppProviderChannel(
        api_key="test-key",
        base_url="https://wa.test",
        client=client,
        sleep=_noop_sleep,
    )

    result = await channel.send(_request())

    assert result.request_id == "wa-1"
    assert captured["json"]["recipient_phone_e164"] == _PHONE
    assert captured["json"]["message"] == _MESSAGE


async def test_sms_provider_send_post_and_parse() -> None:
    import json

    import httpx

    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"request_id": "sms-1", "status": "queued"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    channel = NotifySmsProviderChannel(
        api_key="test-key",
        base_url="https://sms.test",
        client=client,
        sleep=_noop_sleep,
    )

    result = await channel.send(_request())

    assert result.request_id == "sms-1"
    assert captured["json"]["recipient_phone_e164"] == _PHONE
    assert captured["json"]["message"] == _MESSAGE


def test_backoff_delay_grows_exponentially() -> None:
    assert mock_backoff_delay(0) == 0.0
    assert mock_backoff_delay(1) >= 1.0
    assert mock_backoff_delay(2) >= 2.0
    assert mock_backoff_delay(3) >= 4.0


# --- circuit breaker ----------------------------------------------------------


def test_breaker_starts_closed_and_allows_requests() -> None:
    breaker = CircuitBreaker(integration="EXT-003", threshold=3, cooldown_seconds=30.0)

    assert breaker.state is CircuitBreakerState.CLOSED
    assert breaker.allow_request() is True


def test_breaker_opens_after_threshold_consecutive_failures() -> None:
    breaker = CircuitBreaker(integration="EXT-003", threshold=3, cooldown_seconds=30.0)

    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state is CircuitBreakerState.CLOSED
    breaker.record_failure()

    assert breaker.state is CircuitBreakerState.OPEN
    assert breaker.allow_request() is False


def test_breaker_probe_after_cooldown(fake_clock) -> None:
    breaker = CircuitBreaker(
        integration="EXT-003", threshold=2, cooldown_seconds=30.0, clock=fake_clock
    )
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state is CircuitBreakerState.OPEN

    fake_clock.advance(30.0)
    assert breaker.allow_request() is True
    assert breaker.state is CircuitBreakerState.HALF_OPEN


async def test_breaker_channel_refuses_without_calling_provider_when_open() -> None:
    breaker = CircuitBreaker(integration="EXT-003", threshold=2, cooldown_seconds=30.0)
    breaker.record_failure()
    breaker.record_failure()
    channel = CircuitBreakerChannel(MockWhatsAppChannel(), breaker)

    with pytest.raises(NotificationDeliveryError, match="circuit breaker is open"):
        await channel.send(_request())


# --- delivery queue (mirror test_iam_sms_adapter delivery-queue tests) --------


async def test_delivery_queue_swallows_failure_after_retries() -> None:
    queue = NotificationDeliveryQueue(_FailingChannel())

    queue.enqueue(_request())

    await queue.flush()

    assert queue.pending_count == 0


async def test_delivery_queue_notifies_on_delivery_failure() -> None:
    callback = _RecordingCallback()
    queue = NotificationDeliveryQueue(_FailingChannel(), on_delivery_failed=callback)

    queue.enqueue(_request())
    await queue.flush()

    assert callback.calls == [_request()]
    assert queue.pending_count == 0


async def test_delivery_queue_does_not_notify_on_success() -> None:
    callback = _RecordingCallback()
    queue = NotificationDeliveryQueue(MockWhatsAppChannel(), on_delivery_failed=callback)

    queue.enqueue(_request())
    await queue.flush()

    assert callback.calls == []
    assert queue.pending_count == 0


async def test_delivery_queue_callback_failure_does_not_break_the_task(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def boom(request: DeliveryRequest) -> None:
        raise RuntimeError("outbox write failed")

    queue = NotificationDeliveryQueue(_FailingChannel(), on_delivery_failed=boom)
    caplog.set_level(logging.ERROR)

    queue.enqueue(_request())
    await queue.flush()

    assert queue.pending_count == 0
    assert "failed to record notification delivery failure" in caplog.text
