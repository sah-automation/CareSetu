"""PHASE-2 T2: EXT-001 SMS adapter + CI mock (ticket #53, FEAT-001).

Acceptance contract from the brief: a single typed send operation behind the
adapter interface; the mock records the sent code per phone for tests and never
logs it; the provider API key comes from config only and the real path is gated
to staging/production; the OTP value never reaches a log line.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from typing import Literal

import httpx
import pydantic
import pytest

from app.config import (
    DEFAULT_SMS_CIRCUIT_BREAKER_COOLDOWN_SECONDS,
    DEFAULT_SMS_CIRCUIT_BREAKER_THRESHOLD,
    DEFAULT_SMS_MAX_RETRIES,
    DEFAULT_SMS_PROVIDER,
    DEFAULT_SMS_TIMEOUT_SECONDS,
    Settings,
    get_settings,
)
from modules.iam.adapters.sms import (
    CircuitBreaker,
    CircuitBreakerSmsAdapter,
    CircuitBreakerState,
    MockSmsAdapter,
    SmsDeliveryQueue,
    SmsProviderAdapter,
    SmsSendRequest,
    SmsSendResult,
    backoff_delay,
    build_sms_adapter,
    mask_phone,
)
from modules.iam.domain.exceptions import SmsDeliveryError

_PHONE = "+919876543210"
_OTP = "123456"
_PROVIDER_KEY = "test-provider-key"

RequestHandler = Callable[[httpx.Request], httpx.Response]


def _request(phone: str = _PHONE, otp: str = _OTP) -> SmsSendRequest:
    return SmsSendRequest(phone_e164=phone, params={"otp": otp})


async def _noop_sleep(delay: float) -> None:
    pass


def _provider_adapter(
    handler: RequestHandler,
    *,
    max_retries: int = DEFAULT_SMS_MAX_RETRIES,
) -> SmsProviderAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SmsProviderAdapter(
        api_key=_PROVIDER_KEY,
        base_url="https://sms.test",
        max_retries=max_retries,
        client=client,
        sleep=_noop_sleep,
    )


def _queued_response(request_id: str = "req-1") -> httpx.Response:
    return httpx.Response(200, json={"request_id": request_id, "status": "queued"})


# --- mock implementation -------------------------------------------------


async def test_mock_send_records_code_retrievable_by_phone() -> None:
    adapter = MockSmsAdapter()

    await adapter.send(_request())
    await adapter.send(_request(phone="+919000000000", otp="999999"))

    assert adapter.last_sent_code(_PHONE) == _OTP
    assert adapter.last_sent_code("+919000000000") == "999999"
    assert adapter.sent_count(_PHONE) == 1


async def test_mock_send_returns_typed_result() -> None:
    adapter = MockSmsAdapter()

    result = await adapter.send(_request())

    assert isinstance(result, SmsSendResult)
    assert result.status == "queued"
    assert result.request_id.startswith("mock-")


async def test_mock_last_sent_code_is_most_recent_per_phone() -> None:
    adapter = MockSmsAdapter()

    await adapter.send(_request(otp="111111"))
    await adapter.send(_request(otp="222222"))

    assert adapter.last_sent_code(_PHONE) == "222222"
    assert adapter.sent_count(_PHONE) == 2


def test_mock_last_sent_code_none_when_nothing_sent() -> None:
    adapter = MockSmsAdapter()

    assert adapter.last_sent_code(_PHONE) is None
    assert adapter.sent_count(_PHONE) == 0


async def test_mock_send_never_logs_the_otp(caplog: pytest.LogCaptureFixture) -> None:
    adapter = MockSmsAdapter()
    caplog.set_level(logging.DEBUG)

    await adapter.send(_request(otp="654321"))

    assert "654321" not in caplog.text
    assert "654321" not in str(caplog.records)


# --- config gating -------------------------------------------------------


def test_settings_default_to_mock_provider() -> None:
    settings = Settings()

    assert settings.sms_provider == DEFAULT_SMS_PROVIDER
    assert settings.sms_timeout_seconds == DEFAULT_SMS_TIMEOUT_SECONDS
    assert settings.sms_max_retries == DEFAULT_SMS_MAX_RETRIES
    assert settings.sms_api_key == ""
    assert settings.sms_base_url == ""
    assert settings.sms_circuit_breaker_threshold == DEFAULT_SMS_CIRCUIT_BREAKER_THRESHOLD
    assert settings.sms_circuit_breaker_cooldown_seconds == (
        DEFAULT_SMS_CIRCUIT_BREAKER_COOLDOWN_SECONDS
    )


def test_settings_read_sms_values_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENVIRONMENT", "staging")
    monkeypatch.setenv("SMS_PROVIDER", "provider")
    monkeypatch.setenv("SMS_API_KEY", "env-key")
    monkeypatch.setenv("SMS_BASE_URL", "https://sms.example.com")
    monkeypatch.setenv("SMS_TIMEOUT_SECONDS", "5")
    monkeypatch.setenv("SMS_MAX_RETRIES", "2")
    monkeypatch.setenv("SMS_CIRCUIT_BREAKER_THRESHOLD", "7")
    monkeypatch.setenv("SMS_CIRCUIT_BREAKER_COOLDOWN_SECONDS", "45.5")

    settings = get_settings()

    assert settings.sms_provider == "provider"
    assert settings.sms_api_key == "env-key"
    assert settings.sms_base_url == "https://sms.example.com"
    assert settings.sms_timeout_seconds == 5.0
    assert settings.sms_max_retries == 2
    assert settings.sms_circuit_breaker_threshold == 7
    assert settings.sms_circuit_breaker_cooldown_seconds == 45.5


@pytest.mark.parametrize("environment", ["dev", "test"])
def test_settings_refuse_provider_in_dev_test(environment: str) -> None:
    with pytest.raises(
        ValueError,
        match="sms_provider='provider' is gated to staging/production",
    ):
        Settings(
            app_environment=environment,
            sms_provider="provider",
            sms_api_key="k",
            sms_base_url="https://sms.test",
        )


def test_settings_provider_requires_api_key() -> None:
    with pytest.raises(ValueError, match="requires SMS_API_KEY"):
        Settings(
            app_environment="staging",
            sms_provider="provider",
            sms_base_url="https://sms.test",
        )


def test_settings_provider_requires_base_url() -> None:
    with pytest.raises(ValueError, match="requires SMS_BASE_URL"):
        Settings(
            app_environment="staging",
            sms_provider="provider",
            sms_api_key="k",
        )


def test_settings_accept_provider_in_staging() -> None:
    settings = Settings(
        app_environment="staging",
        sms_provider="provider",
        sms_api_key="k",
        sms_base_url="https://sms.test",
    )

    assert settings.sms_provider == "provider"


def test_settings_reject_unknown_provider() -> None:
    with pytest.raises(ValueError, match="unsupported sms_provider"):
        Settings(sms_provider="carrier-pigeon")


@pytest.mark.parametrize("timeout_seconds", [0, -1, 10.5, 30])
def test_settings_refuse_timeout_outside_ext001_discipline(timeout_seconds: float) -> None:
    with pytest.raises(ValueError, match="sms_timeout_seconds must be in \\(0, 10\\]"):
        Settings(sms_timeout_seconds=timeout_seconds)


def test_settings_accept_timeout_boundary_of_ten_seconds() -> None:
    settings = Settings(sms_timeout_seconds=10.0)

    assert settings.sms_timeout_seconds == 10.0


@pytest.mark.parametrize("threshold", [0, -1])
def test_settings_refuse_non_positive_breaker_threshold(threshold: int) -> None:
    with pytest.raises(ValueError, match="sms_circuit_breaker_threshold must be positive"):
        Settings(sms_circuit_breaker_threshold=threshold)


@pytest.mark.parametrize("cooldown_seconds", [0, -1, -30.0])
def test_settings_refuse_non_positive_breaker_cooldown(cooldown_seconds: float) -> None:
    with pytest.raises(ValueError, match="sms_circuit_breaker_cooldown_seconds must be positive"):
        Settings(sms_circuit_breaker_cooldown_seconds=cooldown_seconds)


def test_settings_demo_flags_default_to_production_posture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CORS_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("DEMO_MODE", raising=False)

    settings = get_settings()

    assert settings.cors_allowed_origins == ()
    assert settings.demo_mode is False


def test_settings_read_demo_flags_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        " https://demo.example.com ,, http://other.example.com ",
    )
    monkeypatch.setenv("DEMO_MODE", "true")

    settings = get_settings()

    assert settings.cors_allowed_origins == (
        "https://demo.example.com",
        "http://other.example.com",
    )
    assert settings.demo_mode is True


def test_settings_accept_demo_mode_with_mock_provider() -> None:
    settings = Settings(demo_mode=True)

    assert settings.demo_mode is True
    assert settings.sms_provider == "mock"


def test_settings_refuse_demo_mode_with_real_provider() -> None:
    with pytest.raises(
        ValueError,
        match="demo_mode=True requires sms_provider='mock'",
    ):
        Settings(
            app_environment="production",
            demo_mode=True,
            sms_provider="provider",
            sms_api_key="k",
            sms_base_url="https://sms.test",
        )


@pytest.mark.parametrize(
    ("environment", "demo_mode", "expected"),
    [
        ("dev", False, True),
        ("test", False, True),
        ("production", False, False),
        ("staging", False, False),
        ("production", True, True),
        ("staging", True, True),
    ],
)
def test_mock_otp_readback_enabled_policy(
    environment: str,
    demo_mode: bool,
    expected: bool,
) -> None:
    settings = Settings(app_environment=environment, demo_mode=demo_mode)

    assert settings.mock_otp_readback_enabled is expected


def test_build_sms_adapter_defaults_to_mock() -> None:
    adapter = build_sms_adapter(Settings())

    assert isinstance(adapter, MockSmsAdapter)


def test_build_sms_adapter_wraps_provider_in_circuit_breaker() -> None:
    settings = Settings(
        app_environment="staging",
        sms_provider="provider",
        sms_api_key="k",
        sms_base_url="https://sms.test",
    )

    adapter = build_sms_adapter(settings)

    assert isinstance(adapter, CircuitBreakerSmsAdapter)
    assert isinstance(adapter._adapter, SmsProviderAdapter)
    assert isinstance(adapter._breaker, CircuitBreaker)


# --- request/response typing ---------------------------------------------


def test_send_request_validates_phone_e164() -> None:
    with pytest.raises(pydantic.ValidationError):
        SmsSendRequest(phone_e164="919876543210", params={"otp": _OTP})

    request = SmsSendRequest(phone_e164=_PHONE, params={"otp": _OTP})
    assert request.template == "caresetu_otp"
    assert request.params.ttl_min == 5


# --- provider implementation ---------------------------------------------


async def test_provider_send_sends_typed_payload_with_key() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return _queued_response("req-1")

    adapter = _provider_adapter(handler)

    result = await adapter.send(_request())

    assert result.request_id == "req-1"
    assert result.status == "queued"
    assert seen["url"] == "https://sms.test/v1/send"
    assert seen["authorization"] == f"Bearer {_PROVIDER_KEY}"
    body = seen["body"]
    assert isinstance(body, dict)
    assert body == {
        "phone_e164": _PHONE,
        "template": "caresetu_otp",
        "params": {"otp": _OTP, "ttl_min": 5},
    }


async def test_provider_send_retries_5xx_then_succeeds() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(len(calls) + 1)
        status = (503, 500, 200)[len(calls) - 1]
        return httpx.Response(status, json={"request_id": "req-1", "status": "queued"})

    adapter = _provider_adapter(handler)

    result = await adapter.send(_request())

    assert result.request_id == "req-1"
    assert calls == [1, 2, 3]


async def test_provider_send_retries_rate_limit_then_succeeds() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            return httpx.Response(429)
        return _queued_response()

    adapter = _provider_adapter(handler)

    await adapter.send(_request())

    assert calls == [1, 2]


async def test_provider_send_raises_after_exhausting_retries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    adapter = _provider_adapter(handler)
    caplog.set_level(logging.ERROR)

    with pytest.raises(SmsDeliveryError, match="after 4 attempts") as exc_info:
        await adapter.send(_request(otp="654321"))

    assert exc_info.value.retries_exhausted is True
    assert "654321" not in caplog.text
    assert "+919876543210" not in caplog.text
    assert "patient.auth_failed" in caplog.text


async def test_provider_send_raises_on_network_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    adapter = _provider_adapter(handler)

    with pytest.raises(SmsDeliveryError, match="network error"):
        await adapter.send(_request())


async def test_provider_send_rejects_non_retryable_4xx_immediately() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(len(calls) + 1)
        return httpx.Response(400)

    adapter = _provider_adapter(handler)

    with pytest.raises(SmsDeliveryError, match="HTTP 400") as exc_info:
        await adapter.send(_request())

    assert calls == [1]
    assert exc_info.value.retries_exhausted is False


async def test_provider_send_raises_when_response_missing_request_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "queued"})

    adapter = _provider_adapter(handler)

    with pytest.raises(SmsDeliveryError, match="invalid response payload") as exc_info:
        await adapter.send(_request())

    assert exc_info.value.retries_exhausted is False


async def test_provider_send_raises_on_non_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    adapter = _provider_adapter(handler)

    with pytest.raises(SmsDeliveryError, match="non-JSON") as exc_info:
        await adapter.send(_request())

    assert exc_info.value.retries_exhausted is False


# --- backoff + redaction helpers -----------------------------------------


def test_backoff_delay_grows_exponentially() -> None:
    first = backoff_delay(1)
    second = backoff_delay(2)
    third = backoff_delay(3)

    assert first < second < third
    assert 0.0 < first < 2.0


def test_mask_phone_redacts_middle_digits() -> None:
    masked = mask_phone(_PHONE)

    assert masked.startswith("+91")
    assert masked.endswith("10")
    assert _PHONE not in masked
    assert re.fullmatch(r"\+[0-9]{2}\.\.\.[0-9]{2}", masked)


# --- background delivery queue (PHASE-2 REM T4, #86) ------------------------


class _BlockingSmsAdapter:
    """Adapter whose send blocks until released, to prove enqueue is non-blocking."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.sent: list[SmsSendRequest] = []

    async def send(self, request: SmsSendRequest) -> SmsSendResult:
        self.sent.append(request)
        self.started.set()
        await self.release.wait()
        return SmsSendResult(request_id=f"slow-{len(self.sent)}", status="queued")


class _FailingSmsAdapter:
    """Adapter whose send always fails, to prove failures never reach the caller."""

    async def send(self, request: SmsSendRequest) -> SmsSendResult:
        raise SmsDeliveryError("EXT-001 unavailable")


class _UnexpectedFailureSmsAdapter:
    """Adapter that fails with a non-delivery error (a provider-side bug)."""

    async def send(self, request: SmsSendRequest) -> SmsSendResult:
        raise RuntimeError("provider bug")


class _RejectedSmsAdapter:
    """Adapter that gives up immediately without retrying (a 4xx rejection)."""

    async def send(self, request: SmsSendRequest) -> SmsSendResult:
        raise SmsDeliveryError("EXT-001 send rejected with HTTP 400", retries_exhausted=False)


class _RecordingCallback:
    """Records the requests handed to an ``on_delivery_failed`` callback."""

    def __init__(self) -> None:
        self.calls: list[SmsSendRequest] = []

    async def __call__(self, request: SmsSendRequest) -> None:
        self.calls.append(request)


async def test_delivery_queue_enqueue_returns_before_delivery_completes() -> None:
    adapter = _BlockingSmsAdapter()
    queue = SmsDeliveryQueue(adapter)

    queue.enqueue(_request())
    await adapter.started.wait()

    assert adapter.sent == [_request()]
    assert queue.pending_count == 1
    adapter.release.set()
    await queue.flush()
    assert queue.pending_count == 0


async def test_delivery_queue_flush_awaits_pending_deliveries() -> None:
    adapter = MockSmsAdapter()
    queue = SmsDeliveryQueue(adapter)

    queue.enqueue(_request())
    queue.enqueue(_request(phone="+919000000000", otp="999999"))
    assert queue.pending_count == 2

    await queue.flush()

    assert queue.pending_count == 0
    assert adapter.sent_count(_PHONE) == 1
    assert adapter.last_sent_code("+919000000000") == "999999"


async def test_delivery_queue_swallows_delivery_failure() -> None:
    queue = SmsDeliveryQueue(_FailingSmsAdapter())

    queue.enqueue(_request())

    await queue.flush()

    assert queue.pending_count == 0


async def test_delivery_queue_persistent_failure_logs_the_marker_without_the_otp(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    queue = SmsDeliveryQueue(_provider_adapter(handler))
    caplog.set_level(logging.ERROR)

    queue.enqueue(_request(otp="654321"))
    await queue.flush()

    assert "patient.auth_failed" in caplog.text
    assert "654321" not in caplog.text
    assert "+919876543210" not in caplog.text


# --- delivery-failure emission (PHASE-2 REM T5, #81) --------------------------


async def test_delivery_queue_notifies_on_delivery_failure() -> None:
    callback = _RecordingCallback()
    queue = SmsDeliveryQueue(_FailingSmsAdapter(), on_delivery_failed=callback)

    queue.enqueue(_request())
    await queue.flush()

    assert callback.calls == [_request()]
    assert queue.pending_count == 0


async def test_delivery_queue_does_not_notify_on_success() -> None:
    callback = _RecordingCallback()
    queue = SmsDeliveryQueue(MockSmsAdapter(), on_delivery_failed=callback)

    queue.enqueue(_request())
    await queue.flush()

    assert callback.calls == []
    assert queue.pending_count == 0


async def test_delivery_queue_does_not_notify_on_unexpected_failure() -> None:
    callback = _RecordingCallback()
    queue = SmsDeliveryQueue(_UnexpectedFailureSmsAdapter(), on_delivery_failed=callback)

    queue.enqueue(_request())
    await queue.flush()

    assert callback.calls == []
    assert queue.pending_count == 0


async def test_delivery_queue_does_not_notify_on_non_retryable_rejection() -> None:
    callback = _RecordingCallback()
    queue = SmsDeliveryQueue(_RejectedSmsAdapter(), on_delivery_failed=callback)

    queue.enqueue(_request())
    await queue.flush()

    assert callback.calls == []
    assert queue.pending_count == 0


async def test_delivery_queue_callback_failure_does_not_break_the_task(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def boom(request: SmsSendRequest) -> None:
        raise RuntimeError("outbox write failed")

    queue = SmsDeliveryQueue(_FailingSmsAdapter(), on_delivery_failed=boom)
    caplog.set_level(logging.ERROR)

    queue.enqueue(_request())
    await queue.flush()

    assert queue.pending_count == 0
    assert "failed to record delivery failure" in caplog.text
    assert "+919876543210" not in caplog.text


# --- circuit breaker (PHASE-2 REM FIX 4, #104) --------------------------------


class _SwitchableSmsAdapter:
    """Adapter whose outcome flips at runtime, to prove the breaker gates it."""

    def __init__(self, outcome: Literal["ok", "outage", "reject"] = "ok") -> None:
        self.outcome = outcome
        self.calls = 0

    async def send(self, request: SmsSendRequest) -> SmsSendResult:
        self.calls += 1
        if self.outcome == "outage":
            raise SmsDeliveryError("EXT-001 unavailable")
        if self.outcome == "reject":
            raise SmsDeliveryError("EXT-001 send rejected with HTTP 400", retries_exhausted=False)
        return SmsSendResult(request_id="switch-1", status="queued")


def test_breaker_starts_closed_and_allows_requests() -> None:
    breaker = CircuitBreaker(threshold=3)

    assert breaker.state is CircuitBreakerState.CLOSED
    assert breaker.allow_request() is True


def test_breaker_opens_after_threshold_consecutive_failures() -> None:
    breaker = CircuitBreaker(threshold=3)

    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state is CircuitBreakerState.CLOSED
    assert breaker.allow_request() is True

    breaker.record_failure()

    assert breaker.state is CircuitBreakerState.OPEN
    assert breaker.allow_request() is False


def test_breaker_success_resets_the_failure_count() -> None:
    breaker = CircuitBreaker(threshold=3)

    breaker.record_failure()
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    breaker.record_failure()

    assert breaker.state is CircuitBreakerState.CLOSED
    assert breaker.allow_request() is True


def test_breaker_probe_after_cooldown_reopens_on_failure(fake_clock) -> None:
    breaker = CircuitBreaker(threshold=2, cooldown_seconds=30.0, clock=fake_clock)
    breaker.record_failure()
    breaker.record_failure()
    assert breaker.state is CircuitBreakerState.OPEN

    fake_clock.advance(29.0)
    assert breaker.allow_request() is False

    fake_clock.advance(1.0)
    assert breaker.allow_request() is True
    assert breaker.state is CircuitBreakerState.HALF_OPEN

    breaker.record_failure()

    assert breaker.state is CircuitBreakerState.OPEN
    assert breaker.allow_request() is False


def test_breaker_probe_success_closes_and_logs_recovery(
    fake_clock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    breaker = CircuitBreaker(threshold=1, cooldown_seconds=30.0, clock=fake_clock)
    breaker.record_failure()
    assert breaker.state is CircuitBreakerState.OPEN

    fake_clock.advance(30.0)
    assert breaker.allow_request() is True
    assert breaker.state is CircuitBreakerState.HALF_OPEN

    breaker.record_success()

    assert breaker.state is CircuitBreakerState.CLOSED
    assert "recovered" in caplog.text


async def test_breaker_adapter_refuses_without_calling_provider_when_open() -> None:
    breaker = CircuitBreaker(threshold=1)
    breaker.record_failure()
    spy = _SwitchableSmsAdapter()
    adapter = CircuitBreakerSmsAdapter(spy, breaker)
    assert breaker.state is CircuitBreakerState.OPEN

    with pytest.raises(SmsDeliveryError, match="circuit breaker is open") as exc_info:
        await adapter.send(_request())

    assert exc_info.value.retries_exhausted is True
    assert spy.calls == 0


async def test_breaker_adapter_only_outage_failures_trip_the_breaker() -> None:
    breaker = CircuitBreaker(threshold=2)
    spy = _SwitchableSmsAdapter("reject")
    adapter = CircuitBreakerSmsAdapter(spy, breaker)

    with pytest.raises(SmsDeliveryError, match="HTTP 400"):
        await adapter.send(_request())

    assert breaker.state is CircuitBreakerState.CLOSED
    assert breaker.allow_request() is True


async def test_breaker_adapter_outage_failures_trip_the_breaker() -> None:
    breaker = CircuitBreaker(threshold=2)
    spy = _SwitchableSmsAdapter("outage")
    adapter = CircuitBreakerSmsAdapter(spy, breaker)

    with pytest.raises(SmsDeliveryError):
        await adapter.send(_request())
    with pytest.raises(SmsDeliveryError):
        await adapter.send(_request())

    assert breaker.state is CircuitBreakerState.OPEN
    assert spy.calls == 2


async def test_breaker_adapter_success_resets_the_failure_count() -> None:
    breaker = CircuitBreaker(threshold=2)
    spy = _SwitchableSmsAdapter("outage")
    adapter = CircuitBreakerSmsAdapter(spy, breaker)

    with pytest.raises(SmsDeliveryError):
        await adapter.send(_request())
    spy.outcome = "ok"
    await adapter.send(_request())
    spy.outcome = "outage"
    with pytest.raises(SmsDeliveryError):
        await adapter.send(_request())

    assert breaker.state is CircuitBreakerState.CLOSED
    assert breaker.allow_request() is True


async def test_breaker_adapter_probe_after_cooldown_recovers(fake_clock) -> None:
    breaker = CircuitBreaker(threshold=1, cooldown_seconds=30.0, clock=fake_clock)
    spy = _SwitchableSmsAdapter("outage")
    adapter = CircuitBreakerSmsAdapter(spy, breaker)

    with pytest.raises(SmsDeliveryError):
        await adapter.send(_request())
    assert breaker.state is CircuitBreakerState.OPEN

    spy.outcome = "ok"
    fake_clock.advance(30.0)
    result = await adapter.send(_request())

    assert result.status == "queued"
    assert breaker.state is CircuitBreakerState.CLOSED


async def test_breaker_adapter_probe_is_single_flight(fake_clock) -> None:
    breaker = CircuitBreaker(threshold=1, cooldown_seconds=30.0, clock=fake_clock)
    breaker.record_failure()
    started = asyncio.Event()
    release = asyncio.Event()

    class _GatedProbeAdapter:
        async def send(self, request: SmsSendRequest) -> SmsSendResult:
            started.set()
            await release.wait()
            return SmsSendResult(request_id="probe-1", status="queued")

    adapter = CircuitBreakerSmsAdapter(_GatedProbeAdapter(), breaker)
    fake_clock.advance(30.0)
    probe_task = asyncio.create_task(adapter.send(_request()))
    await started.wait()

    with pytest.raises(SmsDeliveryError, match="probe is already in flight"):
        await adapter.send(_request())

    release.set()
    result = await probe_task

    assert result.status == "queued"
    assert breaker.state is CircuitBreakerState.CLOSED


async def test_breaker_adapter_unexpected_probe_error_clears_the_probe(fake_clock) -> None:
    breaker = CircuitBreaker(threshold=1, cooldown_seconds=30.0, clock=fake_clock)
    breaker.record_failure()

    class _BoomProbeAdapter:
        async def send(self, request: SmsSendRequest) -> SmsSendResult:
            raise RuntimeError("provider bug")

    adapter = CircuitBreakerSmsAdapter(_BoomProbeAdapter(), breaker)
    fake_clock.advance(30.0)

    with pytest.raises(RuntimeError):
        await adapter.send(_request())

    assert adapter._probe_in_flight is False
    assert breaker.state is CircuitBreakerState.HALF_OPEN


async def test_open_breaker_failure_flows_through_queue_degradation_path() -> None:
    breaker = CircuitBreaker(threshold=1)
    breaker.record_failure()
    spy = _SwitchableSmsAdapter()
    callback = _RecordingCallback()
    queue = SmsDeliveryQueue(
        CircuitBreakerSmsAdapter(spy, breaker),
        on_delivery_failed=callback,
    )

    queue.enqueue(_request())
    await queue.flush()

    assert spy.calls == 0
    assert callback.calls == [_request()]
    assert queue.pending_count == 0
