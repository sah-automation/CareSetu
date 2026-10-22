"""OpenTelemetry bootstrap + request-path instrumentation (PHASE-14A A3a, #697).

Stands up the OTel SDK over the **HTTP** OTLP exporter (gRPC is frequently
blocked on PaaS free tiers such as Render) and instruments the request path:
FastAPI server spans, the SQLAlchemy async engine (DB spans) and httpx
(outbound spans for the AI/SMS/WhatsApp/UPI adapters). Gated on
``OTEL_ENABLED`` - with the gate off (or the endpoint unset) nothing is
imported or wired and boot is byte-for-byte unchanged, mirroring the
Langfuse/Redis no-op discipline (plan-phase14-observability §5). An
initialisation failure is logged as a warning and swallowed, so a vendor or
transport problem can never take the API or the worker down.

Initialisation happens once per process at the composition roots: the FastAPI
app (``app/main.py`` ``create_app`` - the OTel ASGI middleware must be added
before the app starts serving, so it cannot be wired from the lifespan) and the
worker (``worker/main.py`` boot). :func:`flush_otel` force-flushes the exporter
on shutdown at both roots, so a Render spin-down does not drop buffered
telemetry.

Resource attributes come from config: ``service.name`` (the process identity -
the A1 ``SERVICE_API`` / ``SERVICE_WORKER`` constants), ``deployment.environment``
from ``APP_ENVIRONMENT`` and ``service.version`` from the A5
``OTEL_SERVICE_VERSION`` git-SHA gate (the single version source shared with A4,
coding-standards §9.2). Sampling is a parent-based ``traceidratio`` sampler
(``OTEL_TRACES_SAMPLER_RATIO``) so a continued trace - an inbound W3C
``traceparent``, or the A2 outbox seam - is never re-sampled differently.

PHI gate - span-attribute allow-list
------------------------------------

:data:`ALLOWED_SPAN_ATTRIBUTES` is a hard allow-list. Every span is run through
:class:`AllowListSpanProcessor` on end, which drops any span-attribute or
span-event-attribute whose key is not on the list before the span reaches the
exporter. A careless caller that sets a phone / OTP / token / free-text /
raw-payload attribute - or an instrumentor that records an exception message -
therefore cannot leak it: the only keys that survive are pseudonymous ids, the
templated route, status codes, model/provider/latency/token counts. The list is
deliberately narrow - losing a non-PHI attribute from a span is cheap, leaking
PHI is not (the same philosophy as A1's key denylist).
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, Protocol, cast

from observability.sentry import resolve_release

if TYPE_CHECKING:
    from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
    from opentelemetry.sdk.trace.export import SpanExporter

    from observability.sentry import SentrySettings

log = logging.getLogger(__name__)

# The stable service id used when a caller does not pass one (the composition
# roots pass the A1 ``SERVICE_API`` / ``SERVICE_WORKER`` identities instead so a
# process has one name across logs and traces).
SERVICE_NAME = "caresetu-backend"

# The instrument scope names (one tracer + one meter for the whole backend).
TRACER_NAME = "caresetu"
METER_NAME = "caresetu"

# Metric instrument names. A single hit/miss counter per outcome carries the
# cache name as a ``cache`` attribute rather than one instrument per cache, so
# the consent and directory caches share one metric family.
_METRIC_HTTP_DURATION = "caresetu.http.server.duration"
_METRIC_HTTP_ERRORS = "caresetu.http.server.errors"
_METRIC_CACHE_HITS = "caresetu.cache.hits"
_METRIC_CACHE_MISSES = "caresetu.cache.misses"
_METRIC_OUTBOX_CLAIMED = "caresetu.outbox.claimed"
_METRIC_OUTBOX_FANNED_OUT = "caresetu.outbox.fanned_out"
_METRIC_OUTBOX_RETRIED = "caresetu.outbox.retried"
_METRIC_OUTBOX_DEAD_LETTERED = "caresetu.outbox.dead_lettered"

# TRUE request concurrency, as a tracing-backend signal (B5 #729, #717 decision
# 17). Requests in flight at this instant - the only honest place saturation
# lives, because a Postgres-resident count would be a snapshot of a number that
# changes every millisecond and would read as though it were the real one. The
# operator reliability read LINKS here rather than storing anything.
#
# The NAME lives here, beside the instrument that records it, because the shared
# package imports nothing from ``modules`` - a metric name the operator's link
# points at is read from THIS side by ``modules.observability.domain.deeplinks``,
# so the dependency runs contract -> instrument and never the other way
# (coding-standards §2).
#
# Unlabelled by design: one series for the whole service. Under the free tier's
# ten-thousand-active-series ceiling that is deliberate - a metric labelled per
# route would spend a series per endpoint to answer a question the total answers.
HTTP_INFLIGHT_METRIC = "caresetu.http.server.inflight"

# Resource attribute keys (OTel semantic conventions).
_ATTR_SERVICE_NAME = "service.name"
_ATTR_SERVICE_VERSION = "service.version"
_ATTR_DEPLOYMENT_ENVIRONMENT = "deployment.environment"

# The documented span-attribute allow-list. Keys not present here are dropped
# before export (module docstring "PHI gate"). Both the legacy and the current
# semantic-convention spellings of a safe key are listed so the filter holds
# across instrumentation versions. Deliberately excluded (each can carry PHI or
# a secret): ``http.url`` / ``http.target`` / ``url.full`` / ``url.query``
# (query strings), ``db.statement`` (bound values), ``http.request.header.*``,
# ``http.user_agent``, ``http.client_ip`` / ``enduser.id``, ``url.path`` (the raw
# untemplated path - only the templated ``http.route`` is kept), and any raw
# payload.
ALLOWED_SPAN_ATTRIBUTES: frozenset[str] = frozenset(
    {
        # HTTP server / client surface (PHI-free fragments only).
        "http.method",
        "http.request.method",
        "http.route",
        "http.status_code",
        "http.response.status_code",
        "http.scheme",
        "http.host",
        "http.server_name",
        "http.flavor",
        "http.request_content_length",
        "http.response_content_length",
        "url.scheme",
        "network.protocol.version",
        "server.address",
        "server.port",
        "net.host.port",
        # Database surface (never the statement or the connection string).
        "db.system",
        "db.system.name",
        "db.name",
        "db.namespace",
        "db.operation",
        "db.operation.name",
        "net.peer.name",
        "net.peer.port",
        # Resource attributes echoed onto spans.
        _ATTR_SERVICE_NAME,
        _ATTR_SERVICE_VERSION,
        _ATTR_DEPLOYMENT_ENVIRONMENT,
        # CareSetu AI span metadata (plan-phase14 §6): pseudonymous ids,
        # provider/model labels, latency and token/cost counters - never prompt
        # or completion text, never patient identity.
        "ai.task_type",
        "ai.provider",
        "ai.model",
        "ai.input_tokens",
        "ai.output_tokens",
        "ai.duration_ms",
        "ai.cost_paise",
        "ai.status",
        "ai.confidence",
        "ai.intake_id",
        "ai.ai_job_id",
        # Async-path surface (A3b): the outbox dispatcher's per-row spans and the
        # APScheduler job spans. The table / event-type / job names are schema
        # and registry labels, never patient data; message ids are opaque UUIDs.
        # Outbox pass counters stay on metrics (caresetu.outbox.*), not on spans,
        # so they are intentionally not allow-listed here.
        "messaging.system",
        "messaging.operation",
        "messaging.destination.name",
        "messaging.message.id",
        "outbox.table",
        "job.name",
        "job.system",
        # Exception event type (the exception class name): safe and useful;
        # the sibling ``exception.message`` / ``exception.stacktrace`` keys are
        # deliberately NOT listed - they can echo PHI and are dropped.
        "exception.type",
    }
)

# Once-per-process guard, mirroring the Langfuse/Sentry singletons: a second
# call is a no-op so repeated ``create_app`` boots in tests never re-wire the
# SDK or re-add the ASGI middleware. ``_enabled`` records whether init actually
# succeeded so the shutdown flush only runs when there is a provider to flush.
_configured = False
_enabled = False
_provider: TracerProvider | None = None

# Metrics state (A3b), gated independently by ``METRICS_ENABLED``. ``_instruments``
# caches lazily-created counters/histograms; because OTel's proxy meter rebinds
# every instrument created before a real provider is set, the cached instruments
# start reporting the moment :func:`init_metrics` wires the provider. When the
# gate is off the meter is the OTel no-op meter and every increment is dropped.
_metrics_configured = False
_metrics_enabled = False
_meter_provider: Any | None = None
_instruments: dict[tuple[str, str], Any] = {}


class OtelSettings(Protocol):
    """The ``Settings`` slice OTel reads, typed structurally for test fakes."""

    @property
    def otel_enabled(self) -> bool: ...

    @property
    def otel_exporter_otlp_endpoint(self) -> str: ...

    @property
    def otel_exporter_otlp_headers(self) -> tuple[str, ...]: ...

    @property
    def otel_traces_sampler_ratio(self) -> float: ...

    @property
    def otel_service_version(self) -> str: ...

    @property
    def app_environment(self) -> str: ...

    @property
    def metrics_enabled(self) -> bool: ...


def parse_otlp_headers(headers: Sequence[str]) -> dict[str, str]:
    """Parse the A5 ``OTEL_EXPORTER_OTLP_HEADERS`` CSV into an exporter map.

    Each entry is a ``key=value`` pair (``Authorization=Basic ...``). A blank
    key or an entry without ``=`` is skipped rather than raising, so a
    malformed header can never block boot.
    """
    parsed: dict[str, str] = {}
    for header in headers:
        key, separator, value = header.partition("=")
        if separator and key.strip():
            parsed[key.strip()] = value.strip()
    return parsed


def _allowed_only(attributes: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return ``attributes`` reduced to allow-listed keys."""
    if not attributes:
        return {}
    return {key: value for key, value in attributes.items() if key in ALLOWED_SPAN_ATTRIBUTES}


def apply_span_allow_list(span: ReadableSpan) -> None:
    """Drop every non-allow-listed span and event attribute, in place.

    OTel wraps span attributes in an immutable mapping, so the filtered set is
    reassigned onto the ``ReadableSpan`` before the wrapped processor (and
    therefore the exporter) sees it. Span **events** are scrubbed by the same
    allow-list: the request-path instrumentors call ``record_exception`` on
    failure, which attaches ``exception.message`` / ``exception.stacktrace``
    event attributes that can echo PHI - only ``exception.type`` survives.
    """
    cast(Any, span)._attributes = _allowed_only(span.attributes)

    events = span.events
    if events:
        cast(Any, span)._events = tuple(
            type(event)(
                event.name,
                _allowed_only(event.attributes),
                event.timestamp,
            )
            for event in events
        )


class AllowListSpanProcessor:
    """A ``SpanProcessor`` wrapper enforcing the span-attribute allow-list.

    Wraps a real processor (the batch exporter) and filters each span's
    attributes and event attributes to :data:`ALLOWED_SPAN_ATTRIBUTES` on end,
    before delegating. Duck-typed rather than subclassing ``SpanProcessor`` so
    the SDK is not imported when the OTel gate is off (the "no SDK import on the
    off path" rule); it mirrors the processor protocol - ``on_start``,
    ``_on_ending``, ``on_end``, ``shutdown``, ``force_flush``.
    """

    def __init__(self, delegate: SpanProcessor) -> None:
        self._delegate = delegate

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        self._delegate.on_start(span, parent_context)

    def _on_ending(self, span: Any) -> None:
        # Private hook the SDK calls synchronously as a span ends; delegate it.
        cast(Any, self._delegate)._on_ending(span)

    def on_end(self, span: ReadableSpan) -> None:
        apply_span_allow_list(span)
        self._delegate.on_end(span)

    def shutdown(self) -> None:
        self._delegate.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._delegate.force_flush(timeout_millis)


def _build_otlp_exporter(endpoint: str, headers: Sequence[str]) -> SpanExporter:
    """Build the HTTP OTLP span exporter (deferred import - only when enabled)."""
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(endpoint=endpoint, headers=parse_otlp_headers(headers))


def _instrument_request_path(
    provider: TracerProvider,
    *,
    engine: object | None,
    app: object | None,
) -> None:
    """Instrument httpx, the SQLAlchemy async engine and the FastAPI app.

    A3a covers the request path only; the dispatcher/APScheduler instrumentation
    is A3b. The engine's sync facade is what the SQLAlchemy instrumentor wraps.
    """
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

    HTTPXClientInstrumentor().instrument(tracer_provider=provider)

    if engine is not None:
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

        sync_engine = getattr(engine, "sync_engine", engine)
        SQLAlchemyInstrumentor().instrument(engine=sync_engine, tracer_provider=provider)

    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(cast(Any, app), tracer_provider=provider)


def _build_resource(settings: OtelSettings, service: str) -> Any:
    """Build the OTel resource shared by the tracer and meter providers (A3b).

    ``service.name`` is the process identity, ``deployment.environment`` comes
    from ``APP_ENVIRONMENT`` and ``service.version`` from the A5
    ``OTEL_SERVICE_VERSION`` git-SHA gate (the single version source shared with
    A4). Deferred import - only reachable on the enabled path.
    """
    from opentelemetry.sdk.resources import Resource

    return Resource.create(
        {
            _ATTR_SERVICE_NAME: service,
            _ATTR_DEPLOYMENT_ENVIRONMENT: settings.app_environment,
            _ATTR_SERVICE_VERSION: resolve_release(cast("SentrySettings", settings)),
        }
    )


# --- metrics + async-path spans (A3b, #698) --------------------------------


def get_meter(name: str = METER_NAME) -> Any:
    """Return the OTel meter for ``name``.

    When metrics are off (or the SDK never initialised) this is the OTel proxy
    meter, whose instruments silently drop every measurement - so a counter call
    is always safe and a no-op. Centralised here so the ``METRICS_ENABLED`` gate
    and the instrument allow-list live in one place.
    """
    from opentelemetry import metrics

    return metrics.get_meter(name)


def get_tracer(name: str = TRACER_NAME) -> Any:
    """Return the OTel tracer for ``name`` (the no-op tracer when tracing is off)."""
    from opentelemetry import trace

    return trace.get_tracer(name)


#: The instrument kinds this module can create. A closed set rather than free
#: ``str``, so a typo in a new metric's ``kind=`` is a type error at ``mypy --strict``
#: instead of a counter quietly recording where a histogram was meant to go.
InstrumentKind = Literal["counter", "histogram", "up_down_counter"]


def _instrument(name: str, *, kind: InstrumentKind, unit: str, description: str) -> Any:
    """Lazily create (and cache) one metric instrument from the meter.

    Cached so a request never pays instrument creation twice; the OTel proxy
    meter rebinds a cached instrument when a real provider is set, so an
    instrument created before :func:`init_metrics` still reports afterwards.
    """
    key = (kind, name)
    instrument = _instruments.get(key)
    if instrument is None:
        meter = get_meter()
        if kind == "histogram":
            instrument = meter.create_histogram(name, unit, description)
        elif kind == "up_down_counter":
            # Non-monotonic: the in-flight request count (#729), which is the one
            # figure whose value legitimately goes back down. See
            # ``record_request_inflight`` for why this is not a ``Gauge``.
            instrument = meter.create_up_down_counter(name, unit, description)
        else:
            instrument = meter.create_counter(name, unit, description)
        _instruments[key] = instrument
    return instrument


def record_cache_hit(cache: str) -> None:
    """Increment the cache-hit counter for ``cache``; never raises.

    A pure side-effect next to the existing cache ``try/except`` blocks: the
    call is failure-silent and a no-op under the OTel proxy meter when metrics
    are off, so cache behaviour is unchanged.
    """
    try:
        _instrument(
            _METRIC_CACHE_HITS,
            kind="counter",
            unit="1",
            description="Redis cache hits, by cache",
        ).add(1, {"cache": cache})
    except Exception:
        log.debug("cache hit metric failed", exc_info=True)


def record_cache_miss(cache: str) -> None:
    """Increment the cache-miss counter for ``cache``; never raises (see hit)."""
    try:
        _instrument(
            _METRIC_CACHE_MISSES,
            kind="counter",
            unit="1",
            description="Redis cache misses, by cache",
        ).add(1, {"cache": cache})
    except Exception:
        log.debug("cache miss metric failed", exc_info=True)


def record_request_latency(
    duration_seconds: float, attributes: Mapping[str, Any] | None = None
) -> None:
    """Record one HTTP request's server duration; never raises.

    Attributes are PHI-free by construction (method, templated route, status) -
    the request metrics middleware never attaches a raw path or query string.
    """
    try:
        _instrument(
            _METRIC_HTTP_DURATION,
            kind="histogram",
            unit="s",
            description="HTTP server request duration",
        ).record(duration_seconds, dict(attributes) if attributes else None)
    except Exception:
        log.debug("request latency metric failed", exc_info=True)


def record_request_error(attributes: Mapping[str, Any] | None = None) -> None:
    """Increment the HTTP server error counter; never raises (see latency)."""
    try:
        _instrument(
            _METRIC_HTTP_ERRORS,
            kind="counter",
            unit="1",
            description="HTTP server errors (5xx or raised), by route",
        ).add(1, dict(attributes) if attributes else None)
    except Exception:
        log.debug("request error metric failed", exc_info=True)


def record_request_inflight(delta: int) -> None:
    """Move the in-flight request count by ``delta`` (+1 on entry, -1 on exit); never raises.

    B5 (#729). This is the TRUE concurrency figure the operator reliability read
    links to instead of approximating in Postgres. Recorded in the SAME
    ``_MetricsASGIMiddleware`` that times the request, because the window this
    measure has is exactly that request's: increment before
    ``await self.app(...)`` and decrement in the ``finally``, so a request that
    raises still leaves the count where it started.

    An UpDownCounter, not a synchronous ``Gauge``: a gauge carries an ABSOLUTE
    value, which only one process can know, whereas an up/down delta is summed by
    whatever receives the export. The value is therefore correct as an in-flight
    COUNT in the tracing backend today and stays correct the day the deferred
    multi-instance path is taken, instead of being right only while there is one
    process.

    Unlabelled on purpose - see :data:`HTTP_INFLIGHT_METRIC`. A failure is logged
    and swallowed like every other metric call: telemetry that can take a request
    down is not telemetry.
    """
    try:
        _instrument(
            HTTP_INFLIGHT_METRIC,
            kind="up_down_counter",
            unit="{request}",
            description="HTTP server requests in flight",
        ).add(delta)
    except Exception:
        log.debug("request inflight metric failed", exc_info=True)


def record_outbox_poll(
    *,
    claimed: int = 0,
    fanned_out: int = 0,
    retried: int = 0,
    dead_lettered: int = 0,
) -> None:
    """Record one dispatcher poll-pass outcome as counters; never raises.

    The four counts are exactly the ``TablePollResult`` fields the loop already
    tracks; they become OTLP metrics so worker throughput is observable without
    parsing logs.
    """
    for name, description, value in (
        (_METRIC_OUTBOX_CLAIMED, "Outbox rows claimed", claimed),
        (_METRIC_OUTBOX_FANNED_OUT, "Outbox rows fanned out", fanned_out),
        (_METRIC_OUTBOX_RETRIED, "Outbox rows scheduled for retry", retried),
        (_METRIC_OUTBOX_DEAD_LETTERED, "Outbox rows dead-lettered", dead_lettered),
    ):
        try:
            _instrument(name, kind="counter", unit="1", description=description).add(value)
        except Exception:
            log.debug("outbox metric failed", exc_info=True)


@contextlib.contextmanager
def start_span(
    name: str,
    *,
    traceparent: str | None = None,
    attributes: Mapping[str, Any] | None = None,
) -> Iterator[Any]:
    """Start a span, linked to the propagated W3C context; no-op when off.

    ``traceparent`` is the value stored on an outbox row by the A2 seam (#695):
    when present it is extracted into the parent context, so the worker's span
    continues the originating request's trace instead of starting a detached
    root. With tracing off the manager yields ``None`` and does nothing, so the
    caller's behaviour is unchanged.
    """
    if not _enabled:
        yield None
        return

    from opentelemetry.propagate import extract

    parent = extract({"traceparent": traceparent}) if traceparent else None
    tracer = get_tracer()
    with tracer.start_as_current_span(
        name, context=parent, attributes=dict(attributes or {})
    ) as span:
        yield span


def _request_metric_attributes(scope: Mapping[str, Any], status_code: int) -> dict[str, Any]:
    """PHI-free request dimensions: method, templated route, status code.

    The raw path is deliberately omitted (it can carry ids/query strings); only
    the router's templated ``route.path`` is used, exactly like the span
    allow-list keeps ``http.route`` and drops ``url.path``.
    """
    attributes: dict[str, Any] = {
        "http.request.method": str(scope.get("method", "")),
        "http.response.status_code": status_code,
    }
    route = scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str):
        attributes["http.route"] = path
    return attributes


class _MetricsASGIMiddleware:
    """Pure-ASGI middleware recording request latency + error counters (A3b).

    Added to the FastAPI app only when ``METRICS_ENABLED`` is on. It wraps the
    request so it can time it end to end and read the final status, then records
    the latency histogram and (on a 5xx or a raised exception) the error counter.
    Only PHI-free dimensions are attached (see :func:`_request_metric_attributes`).

    Since B5 (#729) it also moves the in-flight request count (+1 in, -1 in the
    ``finally``), which is the true concurrency figure the operator reliability read
    links to. Same middleware on purpose: the count has to rise the instant the
    request enters and fall the instant it leaves, and this is the only seam that
    sees both edges of a request.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self._app(scope, receive, send)
            return
        started = time.perf_counter()
        status_code = 500
        failed = False
        record_request_inflight(1)

        async def _send(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message.get("type") == "http.response.start":
                status_code = int(message.get("status", 500))
            await send(message)

        try:
            await self._app(scope, receive, _send)
        except Exception:
            failed = True
            raise
        finally:
            attributes = _request_metric_attributes(scope, status_code)
            record_request_latency(time.perf_counter() - started, attributes)
            if failed or status_code >= 500:
                record_request_error(attributes)
            record_request_inflight(-1)


def init_metrics(
    settings: OtelSettings,
    *,
    service: str = SERVICE_NAME,
    metric_reader: Any | None = None,
    app: Any | None = None,
) -> bool:
    """Initialise OTel metrics once per process; never raises, never blocks boot.

    Gated independently by ``METRICS_ENABLED``: when the gate is off (or the
    OTLP endpoint is unset) it returns immediately - no SDK import, no reader,
    no global meter-provider mutation - so the off path is inert. When on, it
    wires an OTLP HTTP metric exporter over the same endpoint/headers as tracing
    and (when an app is supplied) adds the request metrics middleware.

    ``metric_reader`` overrides the periodic OTLP reader (a test seam) so a test
    can export into an in-memory reader. Any SDK failure is logged and swallowed.
    """
    global _metrics_configured, _metrics_enabled, _meter_provider

    if _metrics_configured:
        return _metrics_enabled
    _metrics_configured = True

    if not settings.metrics_enabled:
        log.info("metrics disabled; OTLP metrics export off")
        return False

    endpoint = settings.otel_exporter_otlp_endpoint.strip()
    if not endpoint:
        log.info("metrics endpoint unset; OTLP metrics export off")
        return False

    try:
        from opentelemetry import metrics
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

        reader = (
            metric_reader
            if metric_reader is not None
            else PeriodicExportingMetricReader(
                OTLPMetricExporter(
                    endpoint=endpoint,
                    headers=parse_otlp_headers(settings.otel_exporter_otlp_headers),
                )
            )
        )
        provider = MeterProvider(
            resource=_build_resource(settings, service),
            metric_readers=[reader],
        )
        metrics.set_meter_provider(provider)
        if app is not None:
            app.add_middleware(_MetricsASGIMiddleware)
    except Exception:
        log.warning("metrics init failed; OTLP metrics export disabled", exc_info=True)
        _meter_provider = None
        _metrics_enabled = False
        return False

    _meter_provider = provider
    _metrics_enabled = True
    log.info("metrics initialised (service=%s, env=%s)", service, settings.app_environment)
    return True


def init_otel(
    settings: OtelSettings,
    *,
    service: str = SERVICE_NAME,
    engine: object | None = None,
    app: object | None = None,
    span_exporter: SpanExporter | None = None,
) -> bool:
    """Initialise the OTel SDK once per process; never raises, never blocks boot.

    Returns ``True`` when the SDK was wired. With ``OTEL_ENABLED`` false (or the
    endpoint unset) it returns immediately - no SDK import, no exporter, no
    instrumentor, no global provider mutation - so the off path is inert. Any
    failure from the SDK is logged as a warning and leaves tracing off.

    ``span_exporter`` overrides the HTTP OTLP exporter (a test seam): when one is
    supplied it is wrapped in a synchronous processor for deterministic export.
    """
    global _configured, _enabled, _provider

    if _configured:
        return _enabled
    _configured = True

    # A3b: metrics are gated independently of tracing. Wire them first so a
    # metrics-only deployment (METRICS_ENABLED on, OTEL_ENABLED off) still
    # exports; an app is passed through so the request metrics middleware can be
    # added before the ASGI stack starts.
    if getattr(settings, "metrics_enabled", False):
        init_metrics(settings, service=service, app=app)

    if not settings.otel_enabled:
        log.info("otel disabled; request-path tracing off")
        return False

    endpoint = settings.otel_exporter_otlp_endpoint.strip()
    if not endpoint:
        log.info("otel endpoint unset; request-path tracing off")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        resource = _build_resource(settings, service)
        sampler = ParentBased(root=TraceIdRatioBased(settings.otel_traces_sampler_ratio))
        provider = TracerProvider(resource=resource, sampler=sampler)

        exporter = (
            span_exporter
            if span_exporter is not None
            else _build_otlp_exporter(endpoint, settings.otel_exporter_otlp_headers)
        )
        span_processor = SimpleSpanProcessor if span_exporter is not None else BatchSpanProcessor
        processor = AllowListSpanProcessor(span_processor(exporter))
        provider.add_span_processor(cast("SpanProcessor", processor))
        trace.set_tracer_provider(provider)

        _instrument_request_path(provider, engine=engine, app=app)
    except Exception:
        log.warning("otel init failed; request-path tracing disabled", exc_info=True)
        _provider = None
        _enabled = False
        return False

    _provider = provider
    _enabled = True
    log.info("otel initialised (service=%s, env=%s)", service, settings.app_environment)
    return True


def flush_otel(timeout_millis: int = 5000) -> None:
    """Force-flush then shut down the trace + metric exporters; no-op when off.

    Called at both composition roots during shutdown (same discipline as the
    Sentry flush) so a Render spin-down or restart does not drop buffered
    telemetry. Each provider is flushed independently, so a metrics-only
    deployment still flushes; a flush/shutdown failure is logged and swallowed.
    """
    global _provider, _meter_provider

    if _provider is not None:
        try:
            _provider.force_flush(timeout_millis)
            _provider.shutdown()
        except Exception:
            log.warning("otel trace flush failed", exc_info=True)
        finally:
            _provider = None

    if _meter_provider is not None:
        try:
            _meter_provider.force_flush(timeout_millis)
            _meter_provider.shutdown()
        except Exception:
            log.warning("otel metrics flush failed", exc_info=True)
        finally:
            _meter_provider = None
