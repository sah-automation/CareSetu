"""PHASE-14A A4: Sentry integration + PHI scrub + release tracking (ticket #696).

Covers the ticket's acceptance criteria:

- Sentry initialises when ``SENTRY_DSN`` is set and is inert (no client, no
  raise) when it is empty.
- Events carry ``release`` (the A5 git-SHA gate, else the app version) and the
  request ``trace_id``.
- The ``before_send`` scrub removes the documented PHI/secret denylist from the
  event payload, so a phone / OTP / token value never reaches the outgoing event.
- A vendor init failure never raises - boot is never taken down.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import sentry_sdk

from app.config import APP_VERSION, Settings
from observability import sentry
from observability.logging import REDACTED_VALUE, reset_trace_id, set_trace_id

_PHONE = "+919876543210"
_OTP = "123456"
_TOKEN = "super-secret-token"


@pytest.fixture
def sentry_state(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Reset the once-per-process init guard around each test."""
    monkeypatch.setattr(sentry, "_initialised", False)
    monkeypatch.setattr(sentry, "_enabled", False)
    yield
    reset_trace_id(set_trace_id(None))


def _event() -> dict[str, Any]:
    return {
        "event_id": "abc",
        "level": "error",
        "extra": {
            "phone": _PHONE,
            "otp_code": _OTP,
            "access_token": _TOKEN,
            "actor_id": 7,
        },
        "request": {
            "url": "https://api.invalid/v1/x",
            "data": json.dumps({"phone": _PHONE}),
            "query_string": f"phone={_PHONE}",
            "headers": {"Authorization": f"Bearer {_TOKEN}"},
        },
        "contexts": {"auth": {"token": _TOKEN, "scope": "patient"}},
        "breadcrumbs": {"values": [{"data": {"phone": _PHONE, "otp": _OTP}}]},
        "tags": {"route": "/v1/x"},
    }


def test_init_sentry_is_inert_without_dsn(sentry_state: Any) -> None:
    enabled = sentry.init_sentry(Settings())

    assert enabled is False
    assert sentry._enabled is False
    assert sentry_sdk.get_client().is_active() is False


def test_init_sentry_leaves_boot_unchanged_when_unset(sentry_state: Any) -> None:
    assert sentry.init_sentry(Settings(sentry_dsn="")) is False
    assert sentry.init_sentry(Settings(sentry_dsn="   ")) is False


def test_init_sentry_configures_release_sample_rate_and_scrub(
    sentry_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def fake_init(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(sentry_sdk, "init", fake_init)

    enabled = sentry.init_sentry(
        Settings(
            sentry_dsn="https://public@example.com/1",
            sentry_traces_sample_rate=0.25,
            otel_service_version="abc1234",
        )
    )

    assert enabled is True
    assert captured["dsn"] == "https://public@example.com/1"
    assert captured["release"] == "abc1234"
    assert captured["traces_sample_rate"] == 0.25
    assert captured["before_send"] is sentry.scrub_event
    assert captured["before_send_transaction"] is sentry.scrub_event
    assert captured["send_default_pii"] is False


def test_init_sentry_is_once_per_process(
    sentry_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def fake_init(**kwargs: Any) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(sentry_sdk, "init", fake_init)
    settings = Settings(sentry_dsn="https://public@example.com/1")

    assert sentry.init_sentry(settings) is True
    assert sentry.init_sentry(settings) is True

    assert calls == 1


def test_init_sentry_never_raises_on_vendor_failure(
    sentry_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(**kwargs: Any) -> None:
        raise RuntimeError("vendor transport exploded")

    monkeypatch.setattr(sentry_sdk, "init", boom)

    assert sentry.init_sentry(Settings(sentry_dsn="https://public@example.com/1")) is False
    assert sentry._enabled is False


def test_resolve_release_prefers_git_sha_gate_then_app_version() -> None:
    assert sentry.resolve_release(Settings(otel_service_version="deadbee")) == "deadbee"
    assert sentry.resolve_release(Settings(otel_service_version="  ")) == APP_VERSION


def test_scrub_event_removes_the_phi_denylist(sentry_state: Any) -> None:
    event = _event()

    scrubbed = sentry.scrub_event(event, {})

    assert scrubbed is not None
    out = json.dumps(scrubbed)
    assert _PHONE not in out
    assert _OTP not in out
    assert _TOKEN not in out
    assert REDACTED_VALUE in out
    # Non-PHI survives.
    assert scrubbed["extra"]["actor_id"] == 7
    assert scrubbed["tags"]["route"] == "/v1/x"
    assert scrubbed["contexts"]["auth"]["scope"] == "patient"


def test_scrub_event_drops_raw_request_body_and_query_string(sentry_state: Any) -> None:
    scrubbed = sentry.scrub_event(_event(), {})

    assert scrubbed is not None
    assert scrubbed["request"]["data"] == REDACTED_VALUE
    assert scrubbed["request"]["query_string"] == REDACTED_VALUE


def test_scrub_event_attaches_the_context_trace_id(sentry_state: Any) -> None:
    token = set_trace_id("trace-xyz")
    try:
        scrubbed = sentry.scrub_event(_event(), {})
    finally:
        reset_trace_id(token)

    assert scrubbed is not None
    assert scrubbed["tags"]["trace_id"] == "trace-xyz"
    assert scrubbed["tags"]["route"] == "/v1/x"


def test_scrub_event_adds_trace_tag_when_tags_absent(sentry_state: Any) -> None:
    token = set_trace_id("trace-123")
    try:
        scrubbed = sentry.scrub_event({"event_id": "x"}, {})
    finally:
        reset_trace_id(token)

    assert scrubbed is not None
    assert scrubbed["tags"] == {"trace_id": "trace-123"}


def test_flush_sentry_is_noop_when_disabled(
    sentry_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("flush must not be called while disabled")

    monkeypatch.setattr(sentry_sdk, "flush", boom)

    sentry.flush_sentry()


def test_flush_sentry_flushes_when_enabled(
    sentry_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    flushed: list[float] = []

    def fake_flush(timeout: float) -> None:
        flushed.append(timeout)

    monkeypatch.setattr(sentry_sdk, "flush", fake_flush)
    sentry._enabled = True

    sentry.flush_sentry(timeout=3.0)

    assert flushed == [3.0]


def test_flush_sentry_never_raises(sentry_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(timeout: float) -> None:
        raise RuntimeError("flush exploded")

    monkeypatch.setattr(sentry_sdk, "flush", boom)
    sentry._enabled = True

    sentry.flush_sentry()
