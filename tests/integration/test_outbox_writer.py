"""PHASE-1 T2a: transactional outbox writer (ticket #19).

Publishes a typed ``Envelope`` into a throwaway outbox materialized through the
Phase 1 helper (``bus.outbox_ddl``) and asserts exactly one ``pending`` row
lands in the same transaction as the publish. A companion test rolls the
caller's transaction back and asserts the row did not survive - proving the
event is atomic with the state change (ADR-0002 §1). Both tests leave the
database as they found it and skip cleanly when the native PostgreSQL is
unreachable, like the rest of the integration suite.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from bus.envelope import Envelope
from bus.outbox_ddl import materialize_outbox
from bus.outbox_writer import write_outbox

THROWAWAY_OUTBOX = "t2a_throwaway_outbox"


class RoundTripPayload(BaseModel):
    round_trip_id: UUID


async def _materialize(database_url: str, schema: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await materialize_outbox(connection, schema, THROWAWAY_OUTBOX)
    finally:
        await engine.dispose()


async def _publish_and_commit(
    database_url: str, schema: str, envelope: Envelope[BaseModel]
) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await write_outbox(connection, schema, THROWAWAY_OUTBOX, envelope)
    finally:
        await engine.dispose()


async def _publish_and_rollback(
    database_url: str, schema: str, envelope: Envelope[BaseModel]
) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            await write_outbox(connection, schema, THROWAWAY_OUTBOX, envelope)
            await transaction.rollback()
    finally:
        await engine.dispose()


async def _outbox_rows(database_url: str, schema: str) -> list[dict[str, Any]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    f"SELECT id, event_id, event_type, payload, occurred_at, status, "
                    f"attempts, next_attempt_at "
                    f'FROM "{schema}"."{THROWAWAY_OUTBOX}"'
                )
            )
            return [dict(mapping) for mapping in result.mappings().all()]
    finally:
        await engine.dispose()


def test_publish_writes_one_pending_outbox_row(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))

    occurred_at = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    envelope = Envelope[RoundTripPayload](
        event_id=uuid4(),
        event_type="phase1.round_trip",
        occurred_at=occurred_at,
        producer="phase1",
        payload=RoundTripPayload(round_trip_id=uuid4()),
    )

    asyncio.run(_publish_and_commit(database_url, throwaway_schema, envelope))

    rows = asyncio.run(_outbox_rows(database_url, throwaway_schema))
    assert len(rows) == 1
    row = rows[0]
    assert isinstance(row["id"], UUID)
    assert row["event_id"] == envelope.event_id
    assert row["event_type"] == "phase1.round_trip"
    assert row["payload"] == {"round_trip_id": str(envelope.payload.round_trip_id)}
    assert row["occurred_at"] == occurred_at
    assert row["status"] == "pending"
    assert row["attempts"] == 0
    assert row["next_attempt_at"] is None


def test_publish_is_atomic_with_caller_transaction(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))

    envelope = Envelope[RoundTripPayload](
        event_id=uuid4(),
        event_type="phase1.round_trip",
        producer="phase1",
        payload=RoundTripPayload(round_trip_id=uuid4()),
    )

    asyncio.run(_publish_and_rollback(database_url, throwaway_schema, envelope))

    assert asyncio.run(_outbox_rows(database_url, throwaway_schema)) == []
