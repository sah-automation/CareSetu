"""Transactional outbox writer (ADR-0002, PHASE-1 T2a #19).

A module publishes an event by writing it into its own outbox table inside the
same DB transaction as its state change, so a crash between the state change
and dispatch cannot lose the event (ADR-0002 §1). The row is inserted with
``status='pending'``; only the dispatcher moves a row out of ``pending``
(ADR-0002 §2, issue #16 row contract).

The writer is transport plumbing: it serializes the typed envelope into the
outbox row shape and never inspects or interprets the payload.
"""

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncConnection

from bus.envelope import Envelope
from bus.outbox_ddl import OUTBOX_STATUS_PENDING, outbox_table


async def write_outbox(
    connection: AsyncConnection,
    schema: str,
    table_name: str,
    envelope: Envelope[BaseModel],
) -> None:
    """Insert ``envelope`` as a pending row into ``schema.table_name``.

    Runs inside ``connection``'s active transaction - the caller commits or
    rolls back the state change and its event together (ADR-0002 §1).
    """
    table = outbox_table(table_name, schema)
    await connection.execute(
        table.insert().values(
            event_id=envelope.event_id,
            event_type=envelope.event_type,
            payload=envelope.payload.model_dump(mode="json"),
            occurred_at=envelope.occurred_at,
            status=OUTBOX_STATUS_PENDING,
            attempts=0,
        )
    )
