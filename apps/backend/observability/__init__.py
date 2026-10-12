"""CareSetu observability infrastructure (plan-phase7-tracing-prep; PHASE-14A).

Shared cross-module observability support: the Langfuse client singleton that
the AI gateway port (standard A6, Phase 7+) consumes for LLM call tracing, the
structured-logging configuration (A1, #694) that the API, worker and dispatcher
share, the Sentry error-tracking bootstrap (A4, #696) and the OpenTelemetry
request-path bootstrap (A3a, #697). Lives at the top level alongside ``bus``
(also shared infra): it is not a module, has no schema, and imports nothing from
``modules``.
"""

from observability.langfuse_client import get_langfuse_client
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
    AllowListSpanProcessor,
    apply_span_allow_list,
    flush_otel,
    init_otel,
    parse_otlp_headers,
)
from observability.sentry import (
    flush_sentry,
    init_sentry,
    resolve_release,
    scrub_event,
)

__all__ = [
    "ALLOWED_SPAN_ATTRIBUTES",
    "REDACTED_VALUE",
    "REDACTION_KEY_FRAGMENTS",
    "SERVICE_API",
    "SERVICE_WORKER",
    "AllowListSpanProcessor",
    "apply_span_allow_list",
    "configure_logging",
    "flush_otel",
    "flush_sentry",
    "get_langfuse_client",
    "get_trace_id",
    "init_otel",
    "init_sentry",
    "parse_otlp_headers",
    "redact_value",
    "reset_trace_id",
    "resolve_release",
    "scrub_event",
    "set_trace_id",
]
