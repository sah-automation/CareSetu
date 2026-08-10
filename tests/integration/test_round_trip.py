"""PHASE-1 T2c: outbox round-trip against the native PostgreSQL (ticket #21).

The Phase 1 definition-of-done for the async seam (issue #16, ADR-0002): a
synthetic ``phase1.round_trip`` event is published into a throwaway outbox via
the transactional writer, fanned out in-process by ``dispatch`` to an idempotent
subscriber that records its ``consumed_events`` ledger row in its own schema,
then the same ``event_id`` is replayed - and exactly one ledger row remains.
Runs against the local native PostgreSQL with no Docker and skips cleanly when
it is unreachable, like the rest of the integration suite.

The dispatcher poll loop that claims/deletes outbox rows arrives in T3a (#22);
this test pins the seam's external behaviour through the synchronous fan-out
step alone (ADR-0002 §2/§3).
"""

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from bus.dispatch import dispatch
from bus.envelope import Envelope
from bus.ledger import record_consumed_event
from bus.outbox_ddl import materialize_consumed_events, materialize_outbox
from bus.outbox_writer import write_outbox
from bus.registry import Handler, HandlerRegistry

THROWAWAY_SCHEMA = "t2c_throwaway"
THROWAWAY_OUTBOX = "t2c_throwaway_outbox"


class RoundTripPayload(BaseModel):
    round_trip_id: UUID


def _probe_reachability(database_url: str) -> None:
    async def probe() -> None:
        engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        finally:
            await engine.dispose()

    try:
        asyncio.run(probe())
    except Exception:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - install/start the native service")


async def _create_throwaway_schema(database_url: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{THROWAWAY_SCHEMA}"'))
    finally:
        await engine.dispose()


async def _drop_throwaway_schema(database_url: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{THROWAWAY_SCHEMA}" CASCADE'))
    finally:
        await engine.dispose()


async def _materialize(database_url: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await materialize_outbox(connection, THROWAWAY_SCHEMA, THROWAWAY_OUTBOX)
            await materialize_consumed_events(connection, THROWAWAY_SCHEMA)
    finally:
        await engine.dispose()


async def _publish(database_url: str, envelope: Envelope[BaseModel]) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await write_outbox(connection, THROWAWAY_SCHEMA, THROWAWAY_OUTBOX, envelope)
    finally:
        await engine.dispose()


async def _outbox_rows(database_url: str) -> list[dict[str, Any]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(f'SELECT event_id, status FROM "{THROWAWAY_SCHEMA}"."{THROWAWAY_OUTBOX}"')
            )
            return [dict(mapping) for mapping in result.mappings().all()]
    finally:
        await engine.dispose()


async def _ledger_rows(database_url: str) -> int:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            count = await connection.scalar(
                text(f'SELECT COUNT(*) FROM "{THROWAWAY_SCHEMA}".consumed_events')
            )
            return int(count or 0)
    finally:
        await engine.dispose()


def _idempotent_subscriber(database_url: str) -> Handler:
    """A handler that records its ledger row inside its own processing transaction.

    Mirrors ADR-0002 §3: the subscriber's ``consumed_events`` row is its delivery
    record; replaying a delivered ``event_id`` is a no-op because the ledger
    primary key makes the re-insert a conflict.
    """

    async def handler(envelope: Envelope[BaseModel]) -> None:
        engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection, connection.begin():
                await record_consumed_event(
                    connection,
                    THROWAWAY_SCHEMA,
                    envelope,
                    handler_result={"delivered": True},
                )
        finally:
            await engine.dispose()

    return handler


def test_round_trip_publish_dispatch_replay_dedupes(database_url: str) -> None:
    _probe_reachability(database_url)

    created = False
    try:
        asyncio.run(_create_throwaway_schema(database_url))
        created = True
        asyncio.run(_materialize(database_url))

        envelope = Envelope[RoundTripPayload](
            event_id=uuid4(),
            event_type="phase1.round_trip",
            producer="phase1",
            payload=RoundTripPayload(round_trip_id=uuid4()),
        )

        # Publish: exactly one pending outbox row lands in the same transaction.
        asyncio.run(_publish(database_url, envelope))
        outbox_rows = asyncio.run(_outbox_rows(database_url))
        assert len(outbox_rows) == 1
        assert outbox_rows[0]["event_id"] == envelope.event_id
        assert outbox_rows[0]["status"] == "pending"

        # Dispatch/fan-out: the idempotent subscriber records its ledger row.
        registry = HandlerRegistry()
        registry.register("phase1.round_trip", _idempotent_subscriber(database_url))

        first_delivery = asyncio.run(dispatch(registry, envelope))
        assert first_delivery.all_succeeded
        assert asyncio.run(_ledger_rows(database_url)) == 1

        # Replay the same event_id: still exactly one ledger row.
        replay = asyncio.run(dispatch(registry, envelope))
        assert replay.all_succeeded
        assert asyncio.run(_ledger_rows(database_url)) == 1
    finally:
        if created:
            asyncio.run(_drop_throwaway_schema(database_url))
