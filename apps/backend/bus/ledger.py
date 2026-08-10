"""Idempotent-subscriber ``consumed_events`` ledger helper (ADR-0002, PHASE-1 T2b #20).

Each subscriber records ``event_id`` in its own ``consumed_events`` ledger - in
its own schema (ADR-0003) - before applying effects, so replaying a delivered
event is a no-op (ADR-0002 §3, issue #16). The helper is the primitive handlers
use: it inserts the delivery row with ``ON CONFLICT DO NOTHING`` on the
``event_id`` primary key and reports whether the row was newly written. A
handler treats a ``False`` return as a replay and skips its effects.

The helper is transport plumbing (like ``bus.outbox_writer``): it serializes
the envelope into the ledger row shape. The ledger itself lives with the
subscriber, never shared across modules.
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.envelope import Envelope
from bus.outbox_ddl import consumed_events_table


async def record_consumed_event(
    connection: AsyncConnection,
    schema: str,
    envelope: Envelope[BaseModel],
    handler_result: Mapping[str, object] | None = None,
) -> bool:
    """Record ``envelope`` in ``schema.consumed_events`` and report dedupe.

    Runs inside ``connection``'s active transaction - the caller commits or
    rolls back the ledger row together with the handler's effects (ADR-0002
    §3). Returns ``True`` when the row was newly inserted (first delivery) and
    ``False`` when ``event_id`` was already recorded (a replay).
    """
    table = consumed_events_table(schema)
    statement = (
        insert(table)
        .values(
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            processed_at=datetime.now(UTC),
            handler_result=handler_result,
        )
        .on_conflict_do_nothing(index_elements=["event_id"])
    )
    result = await connection.execute(statement)
    return result.rowcount == 1
