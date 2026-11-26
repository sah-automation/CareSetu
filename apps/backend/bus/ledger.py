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

``handler_result`` is free-form JSON the CALLER fills - the handler's own name
    today, plus the pseudonymous actor key for a consumer that counts distinct actors
    from this ledger rather than from a table of its own (#729's recent-activity
    figure). Nothing structured is parsed back out of it here: the ledger's contract
    is the ``event_id`` dedupe, and a consumer that wants a number keeps its own
    reader over its own copy of the row.

    :data:`HANDLER_RESULT_ACTOR_KEY` names that one structured key. It lives here,
    beside the writer, because the writer and the reader are the two halves of a
    contract the ledger does not enforce: a subscriber that writes ``actor_key`` and
    a subscriber that counts ``->'actor_key'`` must not spell it differently, and a
    silent rename would show up only as a board reading zero.
"""

from collections.abc import Mapping
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.envelope import Envelope
from bus.outbox_ddl import consumed_events_table

#: The ``handler_result`` key a handler fills with its pseudonymous actor key, and
#: the reader of a recent-activity count selects on. A HASH, never the raw actor
#: reference: the ledger is durable and an operator read must not be able to
#: de-anonymize it.
HANDLER_RESULT_ACTOR_KEY = "actor_key"


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
