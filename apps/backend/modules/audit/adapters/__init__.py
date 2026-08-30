"""MOD-011: event handlers for the ``audit`` module (coding-standards §2).

``register_handlers`` is the composition-root seam (PHASE-1 T4, #30):
the worker entrypoint calls it to register this module's handlers on the
shared ``HandlerRegistry``. PHASE-4 T4 (#239) registers the audit engine's
first real subscriber: ``audit.event`` -> append one regulated act to the
hash-chained ``audit_events`` ledger.

The handler is idempotent (ADR-0002 §3): its ``consumed_events`` ledger row is
written in the SAME transaction as the append, so replaying a delivered
``event_id`` is a no-op and a crash rolls both back together.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from bus.envelope import Envelope
from bus.events import EVENT_AUDIT_EVENT
from bus.ledger import record_consumed_event
from bus.registry import HandlerRegistry
from modules.audit.domain.consumer import AuditEventPayload, is_appended_act
from modules.audit.facade import AUDIT_SCHEMA, append_audit_event

_T = TypeVar("_T", bound=BaseModel)


def _delivery_engine() -> AsyncEngine:
    """A short-lived engine for one delivery (the round-trip harness pattern).

    The composition root passes only the registry to ``register_handlers``,
    so the handler resolves the shared settings lazily at delivery time -
    registration stays connection-free for unit tests and the worker boot.
    ``NullPool`` matches every other short-lived engine in the repo.
    """
    return create_async_engine(get_settings().database_url, poolclass=NullPool)


async def _run_handler(
    envelope: Envelope[BaseModel],
    payload_class: type[_T],
    handler_fn: Callable[[AsyncConnection, _T], Awaitable[None]],
    handler_name: str,
) -> None:
    """Run an event handler with the standard engine-lifecycle boilerplate.

    Handles payload extraction, engine creation, ``record_consumed_event``,
    delivery check, and engine disposal. The callback does the unique work.
    """
    raw_payload = envelope.payload
    payload = (
        raw_payload
        if isinstance(raw_payload, payload_class)
        else payload_class.model_validate(raw_payload.model_dump())
    )
    engine = _delivery_engine()
    try:
        async with engine.begin() as connection:
            delivered = await record_consumed_event(
                connection,
                AUDIT_SCHEMA,
                envelope,
                handler_result={"handler": handler_name},
            )
            if not delivered:
                return
            await handler_fn(connection, payload)
    finally:
        await engine.dispose()


def register_handlers(registry: HandlerRegistry) -> None:
    """Register the audit module's event handlers + payload models."""
    # MOD-011 owns the payload model for the generic ``audit.event`` carrier
    # (it moved here from MOD-004 in PHASE-4 T4): the dispatcher reconstructs a
    # claimed ``audit.event`` outbox row with this model before fan-out.
    registry.register_payload_model(EVENT_AUDIT_EVENT, AuditEventPayload)

    async def append_audit_act(envelope: Envelope[BaseModel]) -> None:
        """Consume ``audit.event``: append one regulated act to the hash chain.

        Ledger first, filter and append second, one transaction: a redelivered
        ``event_id`` finds its ledger row and skips the append; a crash between
        the writes rolls back together, so the event's next delivery retries
        cleanly (at-least-once). Operational acts pass the ledger row (the event
        was consumed) but are silently skipped - only a regulated act is
        appended to ``audit_events``.
        """

        async def _impl(connection: AsyncConnection, payload: AuditEventPayload) -> None:
            if not is_appended_act(payload):
                return
            await append_audit_event(
                connection,
                payload,
                envelope.producer,
                envelope.occurred_at,
            )

        await _run_handler(envelope, AuditEventPayload, _impl, "append_audit_act")

    registry.register(EVENT_AUDIT_EVENT, append_audit_act)
