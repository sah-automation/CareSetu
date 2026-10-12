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

import logging
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol, cast

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

    if not settings.otel_enabled:
        log.info("otel disabled; request-path tracing off")
        return False

    endpoint = settings.otel_exporter_otlp_endpoint.strip()
    if not endpoint:
        log.info("otel endpoint unset; request-path tracing off")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

        resource = Resource.create(
            {
                _ATTR_SERVICE_NAME: service,
                _ATTR_DEPLOYMENT_ENVIRONMENT: settings.app_environment,
                _ATTR_SERVICE_VERSION: resolve_release(cast("SentrySettings", settings)),
            }
        )
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
    """Force-flush then shut down the exporter; a no-op when OTel is off.

    Called at both composition roots during shutdown (same discipline as the
    Sentry flush) so a Render spin-down or restart does not drop buffered
    telemetry. A flush/shutdown failure is logged and swallowed.
    """
    if not _enabled or _provider is None:
        return
    try:
        _provider.force_flush(timeout_millis)
        _provider.shutdown()
    except Exception:
        log.warning("otel flush failed", exc_info=True)
