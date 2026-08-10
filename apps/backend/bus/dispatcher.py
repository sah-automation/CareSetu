"""Dispatcher poll loop over discovered outbox tables (ADR-0002, PHASE-1 T3a #22).

The at-least-once seam's delivery side: a single async loop that polls every
outbox table it is told about, durably claims pending rows ``inflight`` before
any handler runs, reclaims stale ``inflight`` rows after a claim timeout, fans
each row out through ``bus.dispatch.dispatch``, and deletes the row only after
a full successful fan-out (ADR-0002 §2 - the subscriber's ``consumed_events``
ledger is the delivery record, no tombstone).

Discovery is list-based, not module-hardcoded (issue #16): the loop iterates a
``Sequence[OutboxTable]`` supplied by the caller - the worker composition root
(T4, #30) builds it from ``discover_outbox_tables`` over ``MODULE_SCHEMAS``.
The dispatcher is pure transport: it authors no events and its SQL touches
outbox tables only, never domain tables (ADR-0002 §2, coding-standards §2).

Claim model (issue #16): a claim is ``UPDATE ... SET status='inflight'
WHERE status='pending' RETURNING``. The row contract carries no separate
``claimed_at`` column, so the claim deadline is stored in the existing
``next_attempt_at`` column: claiming sets it to ``now + claim_timeout`` and the
stale-inflight reclaim re-pends rows whose ``next_attempt_at`` has passed. A
pending row written by the publisher has ``next_attempt_at = NULL``, which the
poll query also treats as eligible now - so T3b's backoff scheduling (future
``next_attempt_at`` on a ``pending`` row) composes with the same eligibility
predicate.

A row is deleted only when the fan-out actually reached a subscriber and every
handler succeeded - deleting without a subscriber would destroy the event with
no ``consumed_events`` delivery record. A row that cannot be delivered as a
typed envelope (no registered payload model) or has no registered handlers is a
configuration error: it is logged and left for reclaim, never deleted. A
partial fan-out (one failed subscriber) also leaves the row ``inflight``; its
deadline ages it back through the reclaim path, which is the honest at-least-
once behaviour before T3b (#23) layers attempts/backoff and ``dead_letter`` on
top. Deletion is guarded on the claimed deadline so a slow worker cannot delete
a row a sibling worker already reclaimed and re-claimed.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import String, Table, column, delete, func, or_, select, text, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
from sqlalchemy.sql.selectable import Select

from bus.dispatch import dispatch
from bus.envelope import Envelope
from bus.outbox_ddl import (
    OUTBOX_STATUS_INFLIGHT,
    OUTBOX_STATUS_PENDING,
    outbox_table,
)
from bus.registry import HandlerRegistry, PayloadModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutboxTable:
    """A pollable outbox table, located by schema + table name.

    Produced by list-based discovery (``discover_outbox_tables``) or supplied
    directly by the composition root; never hardcoded per module.
    """

    schema: str
    table_name: str


@dataclass(frozen=True)
class OutboxRow:
    """A claimed outbox row, as the loop delivers it (issue #16 row contract).

    ``payload`` is the raw JSONB shape from the row until ``envelope_from_row``
    validates it into the event type's registered Pydantic model - the
    dispatcher is transport and never interprets the payload itself.
    """

    id: UUID
    event_id: UUID
    event_type: str
    payload: dict[str, Any]
    occurred_at: datetime
    next_attempt_at: datetime


@dataclass(frozen=True)
class DispatcherConfig:
    """Tuning knobs for the poll loop (defaults suit the Phase 1 worker)."""

    poll_interval_seconds: float = 1.0
    claim_timeout_seconds: float = 60.0
    batch_size: int = 100


DEFAULT_DISPATCHER_CONFIG = DispatcherConfig()


@dataclass(frozen=True)
class TablePollResult:
    """The outcome of one poll pass over one outbox table, for tests and logs."""

    table: OutboxTable
    stale_reclaimed: int
    claimed: int
    fanned_out: int
    deleted: int


async def discover_outbox_tables(
    connection: AsyncConnection, schemas: Sequence[str]
) -> tuple[OutboxTable, ...]:
    """Discover the ``*_outbox`` tables living in ``schemas``.

    Reads ``information_schema`` for base tables whose name ends in the outbox
    naming pattern (``<module>_outbox``), so the loop's table list is discovered
    rather than hardcoded per module. The 11 module schemas are the canonical
    starting point (``bus.bootstrap.MODULE_SCHEMAS``); the worker may extend the
    list with any additional schema.
    """
    if not schemas:
        return ()
    statement: Select[tuple[str, str]] = (
        select(column("table_schema", String), column("table_name", String))
        .select_from(text("information_schema.tables"))
        .where(column("table_schema", String).in_(list(schemas)))
        .where(column("table_name", String).like(r"%\_outbox"))
        .where(column("table_type", String) == "BASE TABLE")
        .order_by(column("table_schema", String), column("table_name", String))
    )
    result = await connection.execute(statement)
    return tuple(
        OutboxTable(schema=mapping["table_schema"], table_name=mapping["table_name"])
        for mapping in result.mappings().all()
    )


async def reclaim_stale_inflight(
    connection: AsyncConnection, target: Table, config: DispatcherConfig
) -> int:
    """Re-pend rows whose ``inflight`` claim deadline (``next_attempt_at``) has passed.

    A worker that crashed between claim and delete leaves the row ``inflight``
    with a deadline in the past; this step makes it pollable again so the
    delivery is retried (at-least-once, ADR-0002 §2).
    """
    result = await connection.execute(
        update(target)
        .where(
            target.c.status == OUTBOX_STATUS_INFLIGHT,
            target.c.next_attempt_at.is_not(None),
            target.c.next_attempt_at <= func.now(),
        )
        .values(status=OUTBOX_STATUS_PENDING, next_attempt_at=None)
    )
    return int(result.rowcount or 0)


async def claim_pending_rows(
    connection: AsyncConnection,
    target: Table,
    config: DispatcherConfig,
) -> tuple[OutboxRow, ...]:
    """Durably claim eligible pending rows as ``inflight`` and return them.

    The claim is a single ``UPDATE ... WHERE status='pending' RETURNING``
    (issue #16): a ``SELECT ... FOR UPDATE SKIP LOCKED`` in the WHERE clause
    locks up to ``batch_size`` eligible rows (so sibling workers never claim
    the same row) and the update flips them to ``inflight`` with a fresh claim
    deadline. Committed before any handler runs, so a crash after claim leaves
    the row to be reclaimed after the timeout. A row is eligible when
    ``next_attempt_at`` is NULL (published but never claimed) or has passed
    (T3b backoff window).
    """
    candidates = (
        select(target.c.id)
        .where(
            target.c.status == OUTBOX_STATUS_PENDING,
            or_(target.c.next_attempt_at.is_(None), target.c.next_attempt_at <= func.now()),
        )
        .order_by(target.c.occurred_at)
        .limit(config.batch_size)
        .with_for_update(skip_locked=True)
    )
    statement = (
        update(target)
        .where(target.c.id.in_(candidates))
        .values(
            status=OUTBOX_STATUS_INFLIGHT,
            next_attempt_at=func.now() + timedelta(seconds=config.claim_timeout_seconds),
        )
        .returning(
            target.c.id,
            target.c.event_id,
            target.c.event_type,
            target.c.payload,
            target.c.occurred_at,
            target.c.next_attempt_at,
        )
    )
    result = await connection.execute(statement)
    return tuple(_to_outbox_row(mapping) for mapping in result.mappings().all())


def _to_outbox_row(mapping: RowMapping) -> OutboxRow:
    """Build a typed ``OutboxRow`` from a claimed row's RETURNING mapping."""
    return OutboxRow(
        id=cast(UUID, mapping["id"]),
        event_id=cast(UUID, mapping["event_id"]),
        event_type=cast(str, mapping["event_type"]),
        payload=cast(dict[str, Any], mapping["payload"]),
        occurred_at=cast(datetime, mapping["occurred_at"]),
        next_attempt_at=cast(datetime, mapping["next_attempt_at"]),
    )


def envelope_from_row(
    row: OutboxRow, schema: str, payload_model: PayloadModel
) -> Envelope[BaseModel]:
    """Reconstruct a typed ``Envelope`` from a claimed outbox row.

    The row contract (issue #16) does not carry ``producer`` or
    ``schema_version``: the producer is inferred from the outbox's schema (the
    publishing module owns that schema) and ``schema_version`` keeps its
    default. The stored JSONB payload is validated into ``payload_model`` so a
    typed payload - never a raw dict - crosses the seam.
    """
    payload = payload_model.model_validate(row.payload)
    return Envelope[BaseModel](
        event_id=row.event_id,
        event_type=row.event_type,
        occurred_at=row.occurred_at,
        producer=schema,
        payload=payload,
    )


async def delete_outbox_row(
    connection: AsyncConnection,
    target: Table,
    row_id: UUID,
    claimed_deadline: datetime,
) -> bool:
    """Delete a fully delivered row, guarded by its claim (no tombstone).

    The delete matches the row's current status and claim deadline: if a slow
    worker's claim lapsed and a sibling reclaimed and re-claimed the row, the
    deadline no longer matches and this worker does not delete a row another
    worker is delivering.
    """
    result = await connection.execute(
        delete(target).where(
            target.c.id == row_id,
            target.c.status == OUTBOX_STATUS_INFLIGHT,
            target.c.next_attempt_at == claimed_deadline,
        )
    )
    return bool(result.rowcount)


async def process_outbox_table(
    engine: AsyncEngine,
    table: OutboxTable,
    registry: HandlerRegistry,
    config: DispatcherConfig,
) -> TablePollResult:
    """One poll pass over ``table``: reclaim, claim, fan out, delete.

    Reclaim and claim share one transaction (the reclaim's re-pended rows are
    immediately claimable). Each claimed row is reconstructed into a typed
    envelope, fanned out via ``dispatch``, and deleted only when every
    registered subscriber handler succeeded. The dispatcher touches ``table``
    (and each subscriber's own ledger, which handlers write themselves) - never
    domain tables.
    """
    target = outbox_table(table.table_name, table.schema)
    async with engine.begin() as connection:
        stale_reclaimed = await reclaim_stale_inflight(connection, target, config)
        claimed_rows = await claim_pending_rows(connection, target, config)

    fanned_out = 0
    deleted = 0
    for row in claimed_rows:
        payload_model = registry.payload_model_for(row.event_type)
        if payload_model is None:
            logger.error(
                "no payload model registered for event_type %r; leaving outbox row %s for reclaim",
                row.event_type,
                row.event_id,
            )
            continue
        try:
            envelope = envelope_from_row(row, table.schema, payload_model)
            result = await dispatch(registry, envelope)
        except Exception:
            logger.exception(
                "fan-out raised for outbox row %s (%s); leaving it for reclaim",
                row.event_id,
                row.event_type,
            )
            continue
        fanned_out += 1
        if not result.outcomes:
            logger.error(
                "no handlers registered for event_type %r; leaving outbox row %s for reclaim",
                row.event_type,
                row.event_id,
            )
        elif result.all_succeeded:
            async with engine.begin() as connection:
                if await delete_outbox_row(connection, target, row.id, row.next_attempt_at):
                    deleted += 1
                else:
                    logger.info(
                        "outbox row %s was re-claimed by another worker; not deleting",
                        row.event_id,
                    )
        else:
            logger.warning(
                "fan-out incomplete for outbox row %s (%s); leaving it for reclaim",
                row.event_id,
                row.event_type,
            )

    return TablePollResult(
        table=table,
        stale_reclaimed=stale_reclaimed,
        claimed=len(claimed_rows),
        fanned_out=fanned_out,
        deleted=deleted,
    )


async def run_poll_loop(
    engine: AsyncEngine,
    tables: Sequence[OutboxTable],
    registry: HandlerRegistry,
    config: DispatcherConfig = DEFAULT_DISPATCHER_CONFIG,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Poll every discovered outbox table until ``stop_event`` is set.

    One poll pass over all tables, then idle for ``poll_interval_seconds`` and
    repeat. A set ``stop_event`` is honoured between passes - the current pass
    finishes so inflight claims already under delivery drain before shutdown
    (issue #16 user story 19; the worker wires SIGTERM, T4 #30). Exceptions
    propagate: a worker failing to reach its database should crash loudly.
    """
    while stop_event is None or not stop_event.is_set():
        for table in tables:
            await process_outbox_table(engine, table, registry, config)
        await asyncio.sleep(config.poll_interval_seconds)
