"""PHASE-14A A1: structlog JSON logging + PHI redaction (ticket #694).

Covers the ticket's acceptance criteria:

- ``LOG_FORMAT=json`` renders parseable JSON lines, ``console`` renders readable
  (non-JSON) lines.
- Every line carries the service identity and, when one is in the logging
  context, the request/outbox ``trace_id``.
- The redaction processor strips phone / OTP / token / free-text values by key
  before any renderer sees them - for both formats.
- A logging setup failure never raises at boot.
"""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any

import pytest
import structlog
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

import observability.logging as obs_logging
from app.config import Settings
from app.gateway.trace import TraceMiddleware
from observability.logging import (
    REDACTED_VALUE,
    SERVICE_API,
    SERVICE_WORKER,
    configure_logging,
    get_trace_id,
    redact_processor,
    reset_trace_id,
    set_trace_id,
)


@pytest.fixture
def isolated_logging() -> Any:
    """Snapshot and restore root handlers / level and structlog config."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_level = root.level
    saved_config = structlog.get_config()
    saved_installed = obs_logging._installed_handler
    try:
        yield
    finally:
        root.handlers = saved_handlers
        root.setLevel(saved_level)
        structlog.configure(**saved_config)
        obs_logging._installed_handler = saved_installed
        reset_trace_id(set_trace_id(None))


def test_trace_id_context_round_trip() -> None:
    assert get_trace_id() is None
    token = set_trace_id("trace-1")
    assert get_trace_id() == "trace-1"
    reset_trace_id(token)
    assert get_trace_id() is None


def test_json_format_renders_stdlib_logger_line(isolated_logging: Any) -> None:
    stream = io.StringIO()
    configure_logging(Settings(log_format="json"), service=SERVICE_API, stream=stream)

    logging.getLogger("bus.dispatcher").info("processed %s rows", 3)

    payload = json.loads(stream.getvalue().strip())
    assert payload["event"] == "processed 3 rows"
    assert payload["level"] == "info"
    assert payload["logger"] == "bus.dispatcher"
    assert payload["module"] == Path(__file__).stem
    assert payload["service"] == SERVICE_API
    assert payload["timestamp"]


def test_json_format_carries_trace_id_and_context(isolated_logging: Any) -> None:
    stream = io.StringIO()
    configure_logging(Settings(log_format="json"), service=SERVICE_WORKER, stream=stream)
    log = structlog.get_logger("worker.main")

    token = set_trace_id("trace-abc")
    try:
        log.info("outbox fan-out", event_type="care.rx_issued", actor_id="actor-9")
    finally:
        reset_trace_id(token)

    payload = json.loads(stream.getvalue().strip())
    assert payload["trace_id"] == "trace-abc"
    assert payload["service"] == SERVICE_WORKER
    assert payload["event_type"] == "care.rx_issued"
    assert payload["actor_id"] == "actor-9"


def test_json_line_omits_trace_id_without_context(isolated_logging: Any) -> None:
    stream = io.StringIO()
    configure_logging(Settings(log_format="json"), stream=stream)

    logging.getLogger("boot").info("booted")

    payload = json.loads(stream.getvalue().strip())
    assert "trace_id" not in payload
    assert payload["service"] == SERVICE_API


def test_console_format_renders_readable_line(isolated_logging: Any) -> None:
    stream = io.StringIO()
    configure_logging(Settings(log_format="console"), stream=stream)

    logging.getLogger("dev").info("plain readable message")

    out = stream.getvalue()
    assert "plain readable message" in out
    assert "dev" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out.strip())


def test_unknown_format_falls_back_to_console(isolated_logging: Any) -> None:
    class _Settings:
        log_format = "banana"

    stream = io.StringIO()
    configure_logging(_Settings(), stream=stream)

    logging.getLogger("dev").info("still readable")

    assert "still readable" in stream.getvalue()


@pytest.mark.parametrize("log_format", ["json", "console"])
def test_redaction_strips_phi_and_secrets(isolated_logging: Any, log_format: str) -> None:
    stream = io.StringIO()
    configure_logging(Settings(log_format=log_format), stream=stream)
    log = structlog.get_logger("tests.redact")

    log.info(
        "registration attempt",
        phone="+919876543210",
        otp="654321",
        token="super-secret-token",
        free_text="patient reports chest pain",
        actor_id="actor-1",
    )

    out = stream.getvalue()
    assert "+919876543210" not in out
    assert "654321" not in out
    assert "super-secret-token" not in out
    assert "patient reports chest pain" not in out
    assert REDACTED_VALUE in out
    if log_format == "json":
        payload = json.loads(out.strip())
        assert payload["phone"] == REDACTED_VALUE
        assert payload["otp"] == REDACTED_VALUE
        assert payload["token"] == REDACTED_VALUE
        assert payload["free_text"] == REDACTED_VALUE
        assert payload["actor_id"] == "actor-1"


def test_redact_processor_walks_nested_structures() -> None:
    event: dict[str, Any] = {
        "safe": "ok",
        "actor": {"phone": "+91999", "name": "doc"},
        "items": [{"token": "abc"}, {"ok": 1}],
        "meta": ({"otp": "1"},),
    }

    out = redact_processor(None, "info", event)

    assert out["safe"] == "ok"
    assert out["actor"]["phone"] == REDACTED_VALUE
    assert out["actor"]["name"] == "doc"
    assert out["items"][0]["token"] == REDACTED_VALUE
    assert out["items"][1]["ok"] == 1
    assert out["meta"][0]["otp"] == REDACTED_VALUE


def test_configure_logging_never_raises_on_setup_failure(
    isolated_logging: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("structlog exploded")

    monkeypatch.setattr(structlog, "configure", boom)

    configure_logging(Settings(log_format="json"), service=SERVICE_API, force=True)


def test_configure_logging_is_first_call_wins(isolated_logging: Any) -> None:
    first = io.StringIO()
    configure_logging(Settings(log_format="json"), service=SERVICE_API, stream=first)

    # A later call without a test stream (the in-process dispatcher path) must
    # not re-stamp the process with a different service identity.
    configure_logging(Settings(log_format="console"), service=SERVICE_WORKER)
    logging.getLogger("app.main").info("still api")

    payload = json.loads(first.getvalue().strip().splitlines()[-1])
    assert payload["service"] == SERVICE_API


def test_trace_middleware_binds_request_trace_id(isolated_logging: Any) -> None:
    seen: dict[str, str | None] = {}

    async def endpoint(request: Any) -> PlainTextResponse:
        seen["trace_id"] = get_trace_id()
        return PlainTextResponse("ok")

    inner = Starlette(routes=[Route("/", endpoint)])
    client = TestClient(TraceMiddleware(inner))

    client.get("/", headers={"X-Request-Id": "client-trace"})
    assert seen["trace_id"] == "client-trace"

    seen.pop("trace_id")
    client.get("/")
    assert seen["trace_id"]
    assert seen["trace_id"] != "client-trace"
