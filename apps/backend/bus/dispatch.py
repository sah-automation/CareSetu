"""Synchronous dispatch/fan-out step (ADR-0002, PHASE-1 T2b #20).

Given a delivered ``Envelope``, the dispatcher looks up every handler registered
for its ``event_type`` and invokes them in-process. Handler-return-without-
exception = success for that subscriber (ADR-0002 §3). Each handler writes its
own ``consumed_events`` ledger row inside its own processing transaction - the
dispatcher never reads subscriber ledgers (ADR-0003 §3, issue #16).

The dispatcher is pure transport: it authors no events and opens no database
connection here. Failure is per-subscriber - one raising handler is reported in
its outcome and does not stop the sibling handlers (issue #16, #23 fan-out
semantics). The poll loop that drives this step arrives in T3a (#22).
"""

from dataclasses import dataclass

from pydantic import BaseModel

from bus.envelope import Envelope
from bus.registry import Handler, HandlerRegistry


@dataclass(frozen=True)
class HandlerOutcome:
    """The delivery result for a single subscriber handler."""

    handler_name: str
    success: bool
    error: str | None


@dataclass(frozen=True)
class DispatchResult:
    """The fan-out result for one envelope across its registered handlers."""

    event_type: str
    outcomes: tuple[HandlerOutcome, ...]

    @property
    def all_succeeded(self) -> bool:
        """True when every handler succeeded (vacuously true with none)."""
        return all(outcome.success for outcome in self.outcomes)


def _handler_name(handler: Handler) -> str:
    return getattr(handler, "__name__", type(handler).__name__)


async def dispatch(
    registry: HandlerRegistry,
    envelope: Envelope[BaseModel],
) -> DispatchResult:
    """Invoke every handler registered for ``envelope.event_type``.

    A handler that returns without raising is a success for that subscriber;
    a raising handler is isolated and reported as a failed outcome while the
    remaining handlers still run.
    """
    outcomes: list[HandlerOutcome] = []
    for handler in registry.handlers_for(envelope.event_type):
        name = _handler_name(handler)
        try:
            await handler(envelope)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            outcomes.append(HandlerOutcome(handler_name=name, success=False, error=error))
        else:
            outcomes.append(HandlerOutcome(handler_name=name, success=True, error=None))
    return DispatchResult(event_type=envelope.event_type, outcomes=tuple(outcomes))
