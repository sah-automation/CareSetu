"""CareSetu observability infrastructure (plan-phase7-tracing-prep; PHASE-14A).

Shared cross-module observability support: the Langfuse client singleton that
the AI gateway port (standard A6, Phase 7+) consumes for LLM call tracing, and
the structured-logging configuration (A1, #694) that the API, worker and
dispatcher share. Lives at the top level alongside ``bus`` (also shared infra):
it is not a module, has no schema, and imports nothing from ``modules``.
"""

from observability.langfuse_client import get_langfuse_client
from observability.logging import (
    REDACTED_VALUE,
    REDACTION_KEY_FRAGMENTS,
    SERVICE_API,
    SERVICE_WORKER,
    configure_logging,
    get_trace_id,
    reset_trace_id,
    set_trace_id,
)

__all__ = [
    "REDACTED_VALUE",
    "REDACTION_KEY_FRAGMENTS",
    "SERVICE_API",
    "SERVICE_WORKER",
    "configure_logging",
    "get_langfuse_client",
    "get_trace_id",
    "reset_trace_id",
    "set_trace_id",
]
