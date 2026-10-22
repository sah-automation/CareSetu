"""PHASE-14A A3b: OTel dispatcher/scheduler instrumentation + metrics + cache counters (#698).

Covers the ticket's acceptance criteria:

- ``METRICS_ENABLED`` off is inert: no meter provider is wired, the counter
  helpers raise nothing, and boot is unchanged (the vendor gate).
- On, OTel metrics are wired to an OTLP HTTP metric exporter over the same
  endpoint/headers as tracing, against a seam that accepts an in-memory reader.
- Cache hit/miss counters increment on consent and directory cache reads, and
  a miss (including the ``client is None`` path) is counted without raising.
- The dispatcher's per-row span adopts the propagated W3C ``traceparent``, so
  the loop span continues the originating request (the A2/A3b async trace).
- The async-path span attributes ride the existing span-attribute allow-list.
- The shutdown flush covers the meter provider as well as the tracer provider.

The cache tests pin counters through a recording fake meter (no SDK global);
the trace tests use a local ``TracerProvider`` so no global provider is needed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from opentelemetry import metrics as otel_metrics
from opentelemetry.sdk.metrics.export import InMemoryMetricReader, MetricReader
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.config import Settings
from bus import dispatcher as bus_dispatcher
from bus.dispatcher import OutboxRow, OutboxTable
from modules.consent import redis_cache as consent_cache
from modules.partner import directory_cache as directory_cache
from modules.partner.facade import DALTONGANJ_LATITUDE, DALTONGANJ_LONGITUDE
from observability import otel
from observability.otel import (
    ALLOWED_SPAN_ATTRIBUTES,
    METER_NAME,
    TRACER_NAME,
    AllowListSpanProcessor,
    flush_otel,
    init_metrics,
    start_span,
)

_TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
_TRACE_ID = int("4bf92f3577b34da6a3ce929d0e0e4736", 16)


# --- fakes ----------------------------------------------------------------


class _Point:
    def __init__(self, value: int, attributes: dict[str, Any] | None) -> None:
        self.value = value
        self.attributes = attributes


class _RecordingInstrument:
    def __init__(self, name: str) -> None:
        self.name = name
        self.points: list[_Point] = []

    def add(self, value: int, attributes: dict[str, Any] | None = None) -> None:
        self.points.append(_Point(value, attributes))

    def record(self, value: float, attributes: dict[str, Any] | None = None) -> None:
        self.points.append(_Point(int(value), attributes))


class _RecordingMeter:
    def __init__(self) -> None:
        self.instruments: dict[tuple[str, str], _RecordingInstrument] = {}

    def create_counter(  # type: ignore[misc]
        self, name: str, unit: str = "", description: str = ""
    ) -> _RecordingInstrument:
        del unit, description
        return self.instruments.setdefault(("counter", name), _RecordingInstrument(name))

    def create_histogram(  # type: ignore[misc]
        self, name: str, unit: str = "", description: str = ""
    ) -> _RecordingInstrument:
        del unit, description
        return self.instruments.setdefault(("histogram", name), _RecordingInstrument(name))


class _ConsentRedis:
    """The ``hmget`` surface the consent cache touches, with a canned result."""

    def __init__(self, result: list[str | None]) -> None:
        self._result = result

    async def hmget(self, key: str, fields: list[str]) -> list[str | None]:
        del key, fields
        return self._result


class _DirectoryRedis:
    """The ``get`` surface the directory cache touches, with a canned result."""

    def __init__(self, value: str | None) -> None:
        self._value = value

    async def get(self, key: str) -> str | None:
        del key
        return self._value


class _NoOpMetricReader(MetricReader):
    """A thread-free real ``MetricReader`` seam for the reader slot.

    ``PeriodicExportingMetricReader`` is monkeypatched to this when a test
    wants the default reader path without a background export thread; the
    caller's exporter is dropped because the seam never collects.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        super().__init__()

    def _receive_metrics(  # type: ignore[no-untyped-def]
        self, metrics, timeout_millis: int = 10000
    ) -> bool:
        del metrics, timeout_millis
        return True

    def shutdown(self) -> None:
        return


def _outbox_row(traceparent: str | None = None) -> OutboxRow:
    return OutboxRow(
        id=uuid4(),
        event_id=uuid4(),
        event_type="phase1.round_trip",
        payload={"round_trip_id": str(uuid4())},
        occurred_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
        next_attempt_at=datetime(2026, 8, 11, 12, 1, tzinfo=UTC),
        attempts=0,
        traceparent=traceparent,
    )


@pytest.fixture
def otel_worker_state(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Reset the once-per-process OTel + metrics guards around each test."""
    monkeypatch.setattr(otel, "_configured", False)
    monkeypatch.setattr(otel, "_enabled", False)
    monkeypatch.setattr(otel, "_provider", None)
    monkeypatch.setattr(otel, "_metrics_configured", False)
    monkeypatch.setattr(otel, "_metrics_enabled", False)
    monkeypatch.setattr(otel, "_meter_provider", None)
    monkeypatch.setattr(otel, "_instruments", {})
    consent_cache._REDIS_CLIENT = None
    directory_cache._REDIS_CLIENT = None
    yield
    consent_cache._REDIS_CLIENT = None
    directory_cache._REDIS_CLIENT = None


# --- vendor gate: METRICS_ENABLED off = inert ------------------------------


def test_init_metrics_is_inert_when_disabled(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_calls: list[Any] = []
    monkeypatch.setattr(
        otel_metrics, "set_meter_provider", lambda provider: set_calls.append(provider)
    )

    assert init_metrics(Settings()) is False

    assert otel._metrics_enabled is False
    assert otel._meter_provider is None
    assert set_calls == []
    # The counter helpers must be inert no-ops on the off path, never a raise.
    otel.record_cache_hit("consent")
    otel.record_cache_miss("consent")
    otel.record_request_latency(0.1)
    otel.record_request_error()
    otel.record_outbox_poll(claimed=1, dead_lettered=1)


def test_init_metrics_is_inert_when_endpoint_unset(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_calls: list[Any] = []
    monkeypatch.setattr(
        otel_metrics, "set_meter_provider", lambda provider: set_calls.append(provider)
    )

    assert init_metrics(Settings(metrics_enabled=True, otel_exporter_otlp_endpoint="  ")) is False
    assert set_calls == []


def test_init_otel_metrics_gate_off_wires_no_meter_while_tracing_off(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    set_calls: list[Any] = []
    monkeypatch.setattr(
        otel_metrics, "set_meter_provider", lambda provider: set_calls.append(provider)
    )

    assert otel.init_otel(Settings(), engine=object(), app=object()) is False
    assert set_calls == []


# --- metrics on path -------------------------------------------------------


def test_init_metrics_wires_provider_for_the_supplied_reader(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        otel_metrics,
        "set_meter_provider",
        lambda provider: captured.setdefault("provider", provider),
    )

    settings = Settings(
        metrics_enabled=True,
        otel_exporter_otlp_endpoint="https://otlp.invalid/v1/metrics",
    )
    assert (
        init_metrics(settings, service="caresetu-api", metric_reader=InMemoryMetricReader()) is True
    )

    assert otel._metrics_enabled is True
    assert otel._meter_provider is captured["provider"]


def test_init_otel_wires_metrics_even_when_tracing_is_off(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        otel_metrics,
        "set_meter_provider",
        lambda provider: captured.setdefault("provider", provider),
    )
    monkeypatch.setattr(
        "opentelemetry.sdk.metrics.export.PeriodicExportingMetricReader", _NoOpMetricReader
    )

    settings = Settings(
        metrics_enabled=True,
        otel_exporter_otlp_endpoint="https://otlp.invalid/v1/metrics",
    )
    # Tracing is off (OTEL_ENABLED false) so init_otel returns False...
    assert otel.init_otel(settings) is False
    # ...but the independent METRICS_ENABLED gate still wired the meter provider.
    assert "provider" in captured
    assert otel._metrics_enabled is True
    flush_otel()


def test_init_metrics_builds_otlp_metric_exporter_with_parsed_headers(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter",
        _FakeMetricExporter(captured),
    )
    monkeypatch.setattr(
        "opentelemetry.sdk.metrics.export.PeriodicExportingMetricReader", _NoOpMetricReader
    )
    monkeypatch.setattr(otel_metrics, "set_meter_provider", lambda provider: None)

    settings = Settings(
        metrics_enabled=True,
        otel_exporter_otlp_endpoint="https://otlp.invalid/v1/metrics",
        otel_exporter_otlp_headers=("Authorization=Basic dGVzdA==", "x-api-key=k"),
    )
    assert init_metrics(settings) is True

    assert captured["endpoint"] == "https://otlp.invalid/v1/metrics"
    assert captured["headers"] == {"Authorization": "Basic dGVzdA==", "x-api-key": "k"}
    flush_otel()


class _FakeMetricExporter:
    def __init__(self, captured: dict[str, Any]) -> None:
        self._captured = captured

    def __call__(self, endpoint: str, headers: dict[str, str]) -> Any:
        self._captured["endpoint"] = endpoint
        self._captured["headers"] = headers

        class _Exporter:
            @staticmethod
            def force_flush(timeout_millis: int | None = None) -> bool:
                del timeout_millis
                return True

            @staticmethod
            def shutdown() -> None:
                return

        return _Exporter()


# --- cache hit/miss counters ------------------------------------------------


async def test_consent_cache_hit_increments_hit_counter(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    meter = _RecordingMeter()
    monkeypatch.setattr(otel, "get_meter", lambda name=METER_NAME: meter)
    consent_cache._REDIS_CLIENT = _ConsentRedis(["1", "5", "2", "consultations"])

    decision = await consent_cache.get_cached_decision(42, "doctor", "doc-1", "prescriptions")

    assert decision == (True, 5, 2, "consultations")
    hits = meter.instruments[("counter", otel._METRIC_CACHE_HITS)].points
    assert len(hits) == 1
    assert hits[0].value == 1
    assert hits[0].attributes == {"cache": "consent"}
    assert ("counter", otel._METRIC_CACHE_MISSES) not in meter.instruments


async def test_consent_cache_miss_increments_miss_counter(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    meter = _RecordingMeter()
    monkeypatch.setattr(otel, "get_meter", lambda name=METER_NAME: meter)
    consent_cache._REDIS_CLIENT = _ConsentRedis([None, None, None, None])

    assert await consent_cache.get_cached_decision(42, "doctor", "doc-1", "prescriptions") is None

    misses = meter.instruments[("counter", otel._METRIC_CACHE_MISSES)].points
    assert len(misses) == 1
    assert misses[0].value == 1
    assert misses[0].attributes == {"cache": "consent"}
    assert ("counter", otel._METRIC_CACHE_HITS) not in meter.instruments


async def test_directory_cache_hit_and_miss_increment_counters(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    meter = _RecordingMeter()
    monkeypatch.setattr(otel, "get_meter", lambda name=METER_NAME: meter)
    directory_cache._REDIS_CLIENT = _DirectoryRedis('{"items": [], "fell_back": false}')

    hit = await directory_cache.get_cached_search(
        query=None,
        partner_type=None,
        specialty=None,
        latitude=DALTONGANJ_LATITUDE,
        longitude=DALTONGANJ_LONGITUDE,
        expanded=False,
    )
    assert hit is not None
    hits = meter.instruments[("counter", otel._METRIC_CACHE_HITS)].points
    assert len(hits) == 1
    assert hits[0].attributes == {"cache": "directory"}

    directory_cache._REDIS_CLIENT = _DirectoryRedis(None)
    assert (
        await directory_cache.get_cached_search(
            query=None,
            partner_type=None,
            specialty=None,
            latitude=DALTONGANJ_LATITUDE,
            longitude=DALTONGANJ_LONGITUDE,
            expanded=False,
        )
        is None
    )
    misses = meter.instruments[("counter", otel._METRIC_CACHE_MISSES)].points
    assert len(misses) == 1
    assert misses[0].attributes == {"cache": "directory"}


async def test_directory_cache_malformed_payload_counts_as_miss(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    meter = _RecordingMeter()
    monkeypatch.setattr(otel, "get_meter", lambda name=METER_NAME: meter)
    directory_cache._REDIS_CLIENT = _DirectoryRedis("not json")

    assert (
        await directory_cache.get_cached_search(
            query=None,
            partner_type=None,
            specialty=None,
            latitude=DALTONGANJ_LATITUDE,
            longitude=DALTONGANJ_LONGITUDE,
            expanded=False,
        )
        is None
    )
    misses = meter.instruments[("counter", otel._METRIC_CACHE_MISSES)].points
    assert len(misses) == 1
    assert misses[0].attributes == {"cache": "directory"}


async def test_cache_miss_counters_noop_safely_when_redis_absent(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    meter = _RecordingMeter()
    monkeypatch.setattr(otel, "get_meter", lambda name=METER_NAME: meter)
    consent_cache._REDIS_CLIENT = None
    directory_cache._REDIS_CLIENT = None

    # No raise, SQL-fallback miss on both caches, and each miss is counted.
    assert await consent_cache.get_cached_decision(1, "doctor", "d", "prescriptions") is None
    assert (
        await directory_cache.get_cached_search(
            query=None,
            partner_type=None,
            specialty=None,
            latitude=DALTONGANJ_LATITUDE,
            longitude=DALTONGANJ_LONGITUDE,
            expanded=False,
        )
        is None
    )
    misses = meter.instruments[("counter", otel._METRIC_CACHE_MISSES)].points
    assert len(misses) == 2
    assert {miss.attributes["cache"] for miss in misses} == {"consent", "directory"}


# --- outbox / scheduler metrics ---------------------------------------------


def test_record_outbox_poll_increments_counters(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    meter = _RecordingMeter()
    monkeypatch.setattr(otel, "get_meter", lambda name=METER_NAME: meter)

    otel.record_outbox_poll(claimed=3, fanned_out=2, retried=0, dead_lettered=1)

    expected = (
        (otel._METRIC_OUTBOX_CLAIMED, 3),
        (otel._METRIC_OUTBOX_FANNED_OUT, 2),
        (otel._METRIC_OUTBOX_RETRIED, 0),
        (otel._METRIC_OUTBOX_DEAD_LETTERED, 1),
    )
    for name, value in expected:
        points = meter.instruments[("counter", name)].points
        assert len(points) == 1
        assert points[0].value == value
        assert points[0].attributes is None


# --- async-path spans -------------------------------------------------------


def test_start_span_is_noop_when_tracing_is_off(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(otel, "get_tracer", lambda name=TRACER_NAME: provider.get_tracer(name))

    with start_span("outbox.process", traceparent=_TRACEPARENT) as span:
        assert span is None

    assert not exporter.get_finished_spans()


def test_start_span_continues_propagated_traceparent(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(otel, "_enabled", True)
    monkeypatch.setattr(otel, "get_tracer", lambda name=TRACER_NAME: provider.get_tracer(name))

    with start_span("outbox.process", traceparent=_TRACEPARENT) as span:
        assert span is not None

    (finished,) = exporter.get_finished_spans()
    assert finished.context.trace_id == _TRACE_ID
    assert finished.name == "outbox.process"


def test_dispatcher_outbox_row_span_uses_the_rows_traceparent(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loop's per-row span must adopt the row's stored W3C traceparent."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(AllowListSpanProcessor(SimpleSpanProcessor(exporter)))
    monkeypatch.setattr(otel, "_enabled", True)
    monkeypatch.setattr(otel, "get_tracer", lambda name=TRACER_NAME: provider.get_tracer(name))

    row = _outbox_row(traceparent=_TRACEPARENT)
    table = OutboxTable("t_throwaway", "consent_outbox")
    with bus_dispatcher.outbox_row_span(row, table) as span:
        assert span is not None

    (finished,) = exporter.get_finished_spans()
    assert finished.context.trace_id == _TRACE_ID
    # The PHI-free async-path attributes survive the allow-list.
    assert finished.attributes.get("messaging.destination.name") == "consent_outbox"
    assert finished.attributes.get("messaging.message.id") == str(row.event_id)
    assert "patient_phone" not in dict(finished.attributes)


def test_async_path_span_keys_are_allow_listed() -> None:
    for key in (
        "messaging.system",
        "messaging.operation",
        "messaging.destination.name",
        "messaging.message.id",
        "outbox.table",
        "job.name",
        "job.system",
    ):
        assert key in ALLOWED_SPAN_ATTRIBUTES
    # The outbox pass counters are metric instruments (caresetu.outbox.*), and
    # the dispatcher does not attach them to spans, so the allow-list stays tight.
    for key in (
        "messaging.batch.message_count",
        "outbox.claimed",
        "outbox.fanned_out",
        "outbox.retried",
        "outbox.dead_lettered",
        "outbox.stale_reclaimed",
    ):
        assert key not in ALLOWED_SPAN_ATTRIBUTES


# --- shutdown flush ---------------------------------------------------------


def test_flush_otel_flushes_the_meter_provider_too(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
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

    meter_provider = _RecordingProvider()
    tracer_provider = _RecordingProvider()
    monkeypatch.setattr(otel, "_provider", tracer_provider)
    monkeypatch.setattr(otel, "_meter_provider", meter_provider)

    flush_otel(timeout_millis=1234)

    assert tracer_provider.flushed == [1234]
    assert tracer_provider.shutdown_called is True
    assert meter_provider.flushed == [1234]
    assert meter_provider.shutdown_called is True


def test_flush_otel_never_raises_when_metrics_flush_fails(
    otel_worker_state: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Boom:
        def force_flush(self, timeout_millis: int) -> bool:
            del timeout_millis
            raise RuntimeError("metrics flush exploded")

        def shutdown(self) -> None:
            pass

    monkeypatch.setattr(otel, "_provider", None)
    monkeypatch.setattr(otel, "_meter_provider", _Boom())

    flush_otel()
