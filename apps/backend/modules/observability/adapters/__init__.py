"""MOD-013: event handlers for the ``observability`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30):
the worker entrypoint calls it to register this module's handlers on the shared
``HandlerRegistry``. B3 (#701) wires the empty seam only; the telemetry consumer
that accumulates AI usage/cost and business/alert aggregates - recording each
``event_id`` in ``observability.consumed_events`` before applying effects, so a
replayed delivery is a no-op - lands with the B4 consumer ticket.
"""

from __future__ import annotations

from bus.registry import HandlerRegistry


def register_handlers(registry: HandlerRegistry) -> None:
    """Register this module's event handlers on ``registry`` (none yet in B3)."""
