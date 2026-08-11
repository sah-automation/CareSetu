"""MOD-005: event handlers for the ``intake`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30):
the worker entrypoint calls it to register this module's handlers on
the shared ``HandlerRegistry``. No business handlers exist in Phase 1.
"""

from bus.registry import HandlerRegistry


def register_handlers(registry: HandlerRegistry) -> None:
    """Register this module's event handlers on ``registry`` (none yet in Phase 1)."""
