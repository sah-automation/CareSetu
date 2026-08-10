"""HandlerRegistry: event_type -> its handlers (ADR-0002, PHASE-1 T2b #20).

The dispatcher fans each delivered event out in-process to every handler
registered for that ``event_type`` (issue #16, ADR-0002 §2). The registry is
built at the composition root (worker entrypoint) from each module's
``register_handlers`` callbacks - modules never import each other; infra
imports modules only at the composition root.
"""

from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from bus.envelope import Envelope, require_valid_event_type

Handler = Callable[[Envelope[BaseModel]], Awaitable[None]]


class HandlerRegistry:
    """Route an ``event_type`` to all handlers registered for it.

    Registration is additive: one ``event_type`` maps to many handlers and the
    dispatcher invokes every one of them (fan-out to all subscribers). Fan-out
    targets distinct subscribers - each in its own schema (ADR-0003) - so a
    single module registers one handler per ``event_type``; its ``consumed_events``
    ledger keys on ``event_id`` alone and would otherwise treat a sibling handler
    in the same schema as a replay (ADR-0002 §3). A given handler may register
    for several event types, but only once per type so a single event cannot be
    delivered twice to the same subscriber.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}

    def register(self, event_type: str, handler: Handler) -> None:
        """Register ``handler`` for ``event_type`` (raises on a duplicate)."""
        require_valid_event_type(event_type)
        handlers = self._handlers.setdefault(event_type, [])
        if handler in handlers:
            raise ValueError(f"handler already registered for {event_type!r}")
        handlers.append(handler)

    def handlers_for(self, event_type: str) -> tuple[Handler, ...]:
        """Return the handlers registered for ``event_type`` (empty if none)."""
        return tuple(self._handlers.get(event_type, ()))
