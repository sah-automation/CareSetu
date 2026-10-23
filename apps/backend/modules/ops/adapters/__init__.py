"""MOD-014: event handlers for the ``ops`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30):
the worker entrypoint calls it to register this module's handlers on
the shared ``HandlerRegistry``. #764 is the scaffold only; the settings,
history, and feature-flag behavior lands in later PHASE-14B tickets.
"""

from bus.registry import HandlerRegistry


def register_handlers(registry: HandlerRegistry) -> None:
    """Register this module's event handlers on ``registry`` (none yet in #764)."""
