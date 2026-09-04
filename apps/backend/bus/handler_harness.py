"""Shared delivery-engine handler harness (S5 #259).

Consolidates the identical ``_delivery_engine`` + ``_run_handler`` boilerplate
that was copy-pasted across ``audit``, ``iam``, ``notify`` and ``health``
adapter modules into a single canonical home in ``bus``.

The harness handles:
* Payload extraction & re-validation (owner's mirror model)
* Short-lived ``NullPool`` engine lifecycle
* Idempotent ``record_consumed_event`` ledger write (first)
* Handler callback execution (second) inside the same transaction
* Engine disposal (always)

Each consumer imports ``run_handler`` and passes its own schema constant,
keeping payload-model ownership and ``register_payload_model`` calls
isolated in each module's ``register_handlers``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings
from bus.envelope import Envelope
from bus.ledger import record_consumed_event

_T = TypeVar("_T", bound=BaseModel)


def _delivery_engine() -> AsyncEngine:
    """A short-lived engine for one delivery (the round-trip harness pattern).

    The composition root passes only the registry to ``register_handlers``,
    so the handler resolves the shared settings lazily at delivery time -
    registration stays connection-free for unit tests and the worker boot.
    ``NullPool`` matches every other short-lived engine in the repo.
    """
    return create_async_engine(get_settings().database_url, poolclass=NullPool)


async def run_handler(
    envelope: Envelope[BaseModel],
    payload_class: type[_T],
    handler_fn: Callable[[AsyncConnection, _T], Awaitable[None]],
    handler_name: str,
    schema: str,
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
                schema,
                envelope,
                handler_result={"handler": handler_name},
            )
            if not delivered:
                return
            await handler_fn(connection, payload)
    finally:
        await engine.dispose()
