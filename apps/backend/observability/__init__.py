"""CareSetu observability infrastructure (plan-phase7-tracing-prep).

Shared cross-module observability support - today just the Langfuse client
singleton that the AI gateway port (standard A6, Phase 7+) consumes for LLM
call tracing. Lives at the top level alongside ``bus`` (also shared infra): it
is not a module, has no schema, and imports nothing from ``modules``.
"""

from observability.langfuse_client import get_langfuse_client

__all__ = ["get_langfuse_client"]
