"""MOD-013 Observability: typed public sync API.

The only legal cross-module import target for the ``observability``
module (coding-standards §2, ADR-0003). It is telemetry, not a domain
bounded context: typed read methods over the aggregates arrive with the
operator read routes (Batch 1 C1); this scaffold carries no business logic.
"""

from __future__ import annotations


class ObservabilityFacade:
    """Typed public facade for observability (scaffold)."""
