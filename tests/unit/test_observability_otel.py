"""PHASE-14A A3a: OTel bootstrap + request-path instrumentation (ticket #697).

Covers the ticket's acceptance criteria:

- ``OTEL_ENABLED`` off (or the endpoint unset) is inert: no exporter, no
  instrumentor, no global provider mutation, and init never raises.
- On, the SDK is wired with resource attributes from config, a parent-based
  ``traceidratio`` sampler, the HTTP OTLP exporter (endpoint + parsed headers)
  and the request-path instrumentors (FastAPI, SQLAlchemy, httpx).
- The span-attribute allow-list drops a non-allow-listed / PHI-bearing key
  before export, so a careless caller cannot attach one.
- An inbound W3C ``traceparent`` is continued by the server span.
- The exporter force-flushes on shutdown and a flush failure never raises.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import opentelemetry.trace as otel_trace
import pytest
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from app.config import Settings
from observability import otel
from observability.otel import (
    ALLOWED_SPAN_ATTRIBUTES,
    AllowListSpanProcessor,
    flush_otel,
    init_otel,
    parse_otlp_headers,
)

_PHONE = "+919876543210"


@pytest.fixture
def otel_state(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Reset the once-per-process init guard around each test."""
    monkeypatch.setattr(otel, "_configured", False)
    monkeypatch.setattr(otel, "_enabled", False)
    monkeypatch.setattr(otel, "_provider", None)
    yield
    HTTPXClientInstrumentor().uninstrument()


# --- off gate (vendor gate: off = inert) -----------------------------------


def test_init_otel_is_inert_when_disabled(otel_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    set_calls: list[Any] = []

    def _record(provider: Any) -> None:
        set_calls.append(provider)

    monkeypatch.setattr(otel_trace, "set_tracer_provider", _record)

    assert init_otel(Settings(), engine=object(), app=object()) is False

    assert otel._enabled is False
    assert otel._provider is None
    assert set_calls == []
    assert HTTPXClientInstrumentor().is_instrumented_by_opentelemetry is False


def test_init_otel_is_inert_when_endpoint_blank(otel_state: Any) -> None:
    settings = SimpleNamespace(
        otel_enabled=True,
        otel_exporter_otlp_endpoint="   ",
        otel_exporter_otlp_headers=(),
        otel_traces_sampler_ratio=1.0,
        otel_service_version="",
        app_environment="production",
    )

    assert init_otel(settings) is False
    assert otel._enabled is False


# --- span-attribute allow-list (PHI gate) ----------------------------------


def test_allow_list_processor_drops_non_allow_listed_and_phi_keys() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(AllowListSpanProcessor(SimpleSpanProcessor(exporter)))
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("op") as span:
        span.set_attribute("http.route", "/v1/x")
        span.set_attribute("ai.model", "gpt")
        span.set_attribute("patient_phone", _PHONE)
        span.set_attribute("otp_code", "123456")
        span.set_attribute("raw_payload", "free text")

    finished = exporter.get_finished_spans()

    assert len(finished) == 1
    assert dict(finished[0].attributes) == {"http.route": "/v1/x", "ai.model": "gpt"}


def test_allow_list_processor_scrubs_exception_event_attributes() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(AllowListSpanProcessor(SimpleSpanProcessor(exporter)))
    tracer = provider.get_tracer("test")

    with tracer.start_as_current_span("op") as span:
        span.record_exception(ValueError(f"bad phone {_PHONE}"))

    (finished,) = exporter.get_finished_spans()
    (event,) = finished.events

    assert event.name == "exception"
    # ``exception.type`` survives (safe class name); the message/stacktrace that
    # can echo PHI are dropped.
    assert dict(event.attributes) == {"exception.type": "ValueError"}
    assert _PHONE not in str(finished.events)


def test_allow_list_excludes_phi_bearing_keys() -> None:
    for key in (
        "patient_phone",
        "otp_code",
        "access_token",
        "http.url",
        "http.target",
        "url.full",
        "url.query",
        "url.path",
        "db.statement",
        "http.user_agent",
        "http.client_ip",
        "raw_payload",
        "exception.message",
        "exception.stacktrace",
    ):
        assert key not in ALLOWED_SPAN_ATTRIBUTES


def test_parse_otlp_headers_skips_blank_and_malformed_entries() -> None:
    assert parse_otlp_headers(()) == {}
    assert parse_otlp_headers(("noequals", "= ", " ")) == {}
    assert parse_otlp_headers(("Authorization=Basic dGVzdA==", "  x-api-key = k ")) == {
        "Authorization": "Basic dGVzdA==",
        "x-api-key": "k",
    }


# --- propagated traceparent -------------------------------------------------


async def test_request_span_continues_inbound_traceparent() -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    app = FastAPI()

    @app.get("/ping")
    async def ping() -> dict[str, bool]:
        return {"ok": True}

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

    trace_id_hex = "4bf92f3577b34da6a3ce929d0e0e4736"
    traceparent = f"00-{trace_id_hex}-00f067aa0ba902b7-01"
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/ping", headers={"traceparent": traceparent})

    assert response.status_code == 200
    server_spans = [s for s in exporter.get_finished_spans() if s.kind == SpanKind.SERVER]
    assert len(server_spans) == 1
    assert server_spans[0].context.trace_id == int(trace_id_hex, 16)


# --- on path wiring ---------------------------------------------------------


def _noop_instrumentor() -> Any:
    class _Noop:
        def instrument(self, **kwargs: Any) -> None:
            del kwargs

    return _Noop()


def test_init_otel_wires_resource_sampler_and_request_path_instrumentors(
    otel_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    exporter = InMemorySpanExporter()
    captured: dict[str, Any] = {}

    def _capture(provider: Any) -> None:
        captured["provider"] = provider

    monkeypatch.setattr(otel_trace, "set_tracer_provider", _capture)

    httpx_calls: list[dict[str, Any]] = []
    sqlalchemy_calls: list[dict[str, Any]] = []
    fastapi_calls: list[dict[str, Any]] = []

    class _FakeHttpX:
        def instrument(self, **kwargs: Any) -> None:
            httpx_calls.append(kwargs)

    class _FakeSQLAlchemy:
        def instrument(self, **kwargs: Any) -> None:
            sqlalchemy_calls.append(kwargs)

    class _FakeFastAPI:
        @staticmethod
        def instrument_app(app: Any, **kwargs: Any) -> None:
            fastapi_calls.append({"app": app, **kwargs})

    monkeypatch.setattr("opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor", _FakeHttpX)
    monkeypatch.setattr(
        "opentelemetry.instrumentation.sqlalchemy.SQLAlchemyInstrumentor", _FakeSQLAlchemy
    )
    monkeypatch.setattr("opentelemetry.instrumentation.fastapi.FastAPIInstrumentor", _FakeFastAPI)

    settings = Settings(
        otel_enabled=True,
        otel_exporter_otlp_endpoint="https://otlp.invalid/v1/traces",
        otel_service_version="abc1234",
        app_environment="staging",
        otel_traces_sampler_ratio=1.0,
    )
    sync_engine = object()
    engine = SimpleNamespace(sync_engine=sync_engine)
    app = object()

    assert (
        init_otel(settings, service="caresetu-api", engine=engine, app=app, span_exporter=exporter)
        is True
    )

    provider = captured["provider"]
    assert otel._provider is provider
    assert otel._enabled is True

    resource = dict(provider.resource.attributes)
    assert resource["service.name"] == "caresetu-api"
    assert resource["deployment.environment"] == "staging"
    assert resource["service.version"] == "abc1234"

    description = provider.sampler.get_description()
    assert description.startswith("ParentBased")
    assert "TraceIdRatioBased{1.0}" in description

    assert httpx_calls == [{"tracer_provider": provider}]
    assert sqlalchemy_calls == [{"engine": sync_engine, "tracer_provider": provider}]
    assert fastapi_calls == [{"app": app, "tracer_provider": provider}]

    # The wired provider enforces the allow-list before export.
    tracer = provider.get_tracer("test")
    with tracer.start_as_current_span("op") as span:
        span.set_attribute("http.route", "/x")
        span.set_attribute("patient_phone", _PHONE)
    exported = exporter.get_finished_spans()
    assert [dict(s.attributes) for s in exported] == [{"http.route": "/x"}]


def test_init_otel_builds_http_otlp_exporter_with_parsed_headers(
    otel_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    class _FakeExporter:
        def __init__(self, endpoint: str, headers: dict[str, str]) -> None:
            captured["endpoint"] = endpoint
            captured["headers"] = headers

        def export(self, spans: Any) -> None:
            del spans

        def shutdown(self) -> None:
            pass

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            del timeout_millis
            return True

    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter", _FakeExporter
    )
    monkeypatch.setattr(
        "opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor", _noop_instrumentor
    )
    monkeypatch.setattr(otel_trace, "set_tracer_provider", lambda provider: None)

    settings = Settings(
        otel_enabled=True,
        otel_exporter_otlp_endpoint="https://otlp.invalid/v1/traces",
        otel_exporter_otlp_headers=("Authorization=Basic dGVzdA==", "x-api-key=k"),
    )

    assert init_otel(settings) is True

    assert captured["endpoint"] == "https://otlp.invalid/v1/traces"
    assert captured["headers"] == {"Authorization": "Basic dGVzdA==", "x-api-key": "k"}

    # Tear down the batch processor thread the real provider started.
    flush_otel()


def test_init_otel_never_raises_on_vendor_failure(
    otel_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Boom:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs
            raise RuntimeError("vendor transport exploded")

    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter", _Boom
    )

    settings = Settings(
        otel_enabled=True,
        otel_exporter_otlp_endpoint="https://otlp.invalid/v1/traces",
    )

    assert init_otel(settings) is False
    assert otel._enabled is False
    assert otel._provider is None


# --- shutdown flush ---------------------------------------------------------


def test_flush_otel_is_noop_when_disabled(otel_state: Any) -> None:
    flush_otel()


def test_flush_otel_flushes_and_shuts_down_when_enabled(
    otel_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _RecordingProvider:
        def __init__(self) -> None:
            self.flushed: list[int] = []
            self.shutdown_called = False

        def force_flush(self, timeout_millis: int) -> bool:
            self.flushed.append(timeout_millis)
            return True

        def shutdown(self) -> None:
            self.shutdown_called = True

    provider = _RecordingProvider()
    monkeypatch.setattr(otel, "_enabled", True)
    monkeypatch.setattr(otel, "_provider", provider)

    flush_otel(timeout_millis=1234)

    assert provider.flushed == [1234]
    assert provider.shutdown_called is True


def test_flush_otel_never_raises(otel_state: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Boom:
        def force_flush(self, timeout_millis: int) -> bool:
            del timeout_millis
            raise RuntimeError("flush exploded")

        def shutdown(self) -> None:
            pass

    monkeypatch.setattr(otel, "_enabled", True)
    monkeypatch.setattr(otel, "_provider", _Boom())

    flush_otel()
