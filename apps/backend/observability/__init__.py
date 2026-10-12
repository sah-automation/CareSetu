"""CareSetu observability infrastructure (plan-phase7-tracing-prep; PHASE-14A).

Shared cross-module observability support: the Langfuse client singleton that
the AI gateway port (standard A6, Phase 7+) consumes for LLM call tracing, the
structured-logging configuration (A1, #694) that the API, worker and dispatcher
share, the Sentry error-tracking bootstrap (A4, #696) and the OpenTelemetry
request-path bootstrap (A3a, #697). Lives at the top level alongside ``bus``
(also shared infra): it is not a module, has no schema, and imports nothing from
``modules``.
"""

from observability.langfuse_client import (
    flush_langfuse,
    get_configured_client,
    get_langfuse_client,
)
from observability.langfuse_span import (
    ALLOWED_SPAN_METADATA_KEYS,
    SpanMetadataError,
    build_span_metadata,
    set_span_metadata,
)
from observability.logging import (
    REDACTED_VALUE,
    REDACTION_KEY_FRAGMENTS,
    SERVICE_API,
    SERVICE_WORKER,
    configure_logging,
    get_trace_id,
    redact_value,
    reset_trace_id,
    set_trace_id,
)
from observability.otel import (
    ALLOWED_SPAN_ATTRIBUTES,
    METER_NAME,
    TRACER_NAME,
    AllowListSpanProcessor,
    apply_span_allow_list,
    flush_otel,
    get_meter,
    get_tracer,
    init_metrics,
    init_otel,
    parse_otlp_headers,
    record_cache_hit,
    record_cache_miss,
    record_outbox_poll,
    record_request_error,
    record_request_latency,
    start_span,
)
from observability.sentry import (
    flush_sentry,
    init_sentry,
    resolve_release,
    scrub_event,
)

__all__ = [
    "ALLOWED_SPAN_ATTRIBUTES",
    "ALLOWED_SPAN_METADATA_KEYS",
    "METER_NAME",
    "REDACTED_VALUE",
    "REDACTION_KEY_FRAGMENTS",
    "SERVICE_API",
    "SERVICE_WORKER",
    "TRACER_NAME",
    "AllowListSpanProcessor",
    "SpanMetadataError",
    "apply_span_allow_list",
    "build_span_metadata",
    "configure_logging",
    "flush_langfuse",
    "flush_otel",
    "flush_sentry",
    "get_configured_client",
    "get_langfuse_client",
    "get_meter",
    "get_trace_id",
    "get_tracer",
    "init_metrics",
    "init_otel",
    "init_sentry",
    "parse_otlp_headers",
    "record_cache_hit",
    "record_cache_miss",
    "record_outbox_poll",
    "record_request_error",
    "record_request_latency",
    "redact_value",
    "reset_trace_id",
    "resolve_release",
    "scrub_event",
    "set_span_metadata",
    "set_trace_id",
    "start_span",
]
