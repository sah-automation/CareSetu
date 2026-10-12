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

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from bus.dispatch import dispatch
from bus.dispatcher import DispatcherConfig, OutboxTable, process_outbox_table
from bus.envelope import Envelope
from bus.ledger import record_consumed_event
from bus.outbox_ddl import materialize_consumed_events, materialize_outbox
from bus.outbox_writer import write_outbox
from bus.registry import Handler, HandlerRegistry
from observability.logging import (
    get_trace_id,
    reset_trace_id,
    set_trace_id,
    trace_id_from_traceparent,
)

THROWAWAY_OUTBOX = "t2c_throwaway_outbox"


class RoundTripPayload(BaseModel):
    round_trip_id: UUID


async def _materialize(database_url: str, schema: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await materialize_outbox(connection, schema, THROWAWAY_OUTBOX)
            await materialize_consumed_events(connection, schema)
    finally:
        await engine.dispose()


async def _publish(database_url: str, schema: str, envelope: Envelope[BaseModel]) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await write_outbox(connection, schema, THROWAWAY_OUTBOX, envelope)
    finally:
        await engine.dispose()


async def _outbox_rows(database_url: str, schema: str) -> list[dict[str, Any]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(f'SELECT event_id, status, traceparent FROM "{schema}"."{THROWAWAY_OUTBOX}"')
            )
            return [dict(mapping) for mapping in result.mappings().all()]
    finally:
        await engine.dispose()


async def _ledger_rows(database_url: str, schema: str) -> int:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            count = await connection.scalar(
                text(f'SELECT COUNT(*) FROM "{schema}".consumed_events')
            )
            return int(count or 0)
    finally:
        await engine.dispose()


def _idempotent_subscriber(database_url: str, schema: str) -> Handler:
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
                    schema,
                    envelope,
                    handler_result={"delivered": True},
                )
        finally:
            await engine.dispose()

    return handler


def test_round_trip_publish_dispatch_replay_dedupes(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))

    envelope = Envelope[RoundTripPayload](
        event_id=uuid4(),
        event_type="phase1.round_trip",
        producer="phase1",
        payload=RoundTripPayload(round_trip_id=uuid4()),
    )

    # Publish: exactly one pending outbox row lands in the same transaction.
    asyncio.run(_publish(database_url, throwaway_schema, envelope))
    outbox_rows = asyncio.run(_outbox_rows(database_url, throwaway_schema))
    assert len(outbox_rows) == 1
    assert outbox_rows[0]["event_id"] == envelope.event_id
    assert outbox_rows[0]["status"] == "pending"

    # Dispatch/fan-out: the idempotent subscriber records its ledger row.
    registry = HandlerRegistry()
    registry.register("phase1.round_trip", _idempotent_subscriber(database_url, throwaway_schema))

    first_delivery = asyncio.run(dispatch(registry, envelope))
    assert first_delivery.all_succeeded
    assert asyncio.run(_ledger_rows(database_url, throwaway_schema)) == 1

    # Replay the same event_id: still exactly one ledger row.
    replay = asyncio.run(dispatch(registry, envelope))
    assert replay.all_succeeded
    assert asyncio.run(_ledger_rows(database_url, throwaway_schema)) == 1


def test_trace_id_propagates_from_api_through_outbox_to_dispatcher(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    """PHASE-14A A2 (#695): the request trace id survives API -> outbox -> dispatcher.

    A request-scoped trace id is bound here exactly as ``TraceMiddleware`` binds
    it for a real request. The writer embeds it in the outbox row as a W3C
    ``traceparent``; the dispatcher restores it into the logging context before
    the subscriber handler runs, so the worker-side handler observes the
    originating request's id.
    """
    asyncio.run(_materialize(database_url, throwaway_schema))

    envelope = Envelope[RoundTripPayload](
        event_id=uuid4(),
        event_type="phase1.round_trip",
        producer="phase1",
        payload=RoundTripPayload(round_trip_id=uuid4()),
    )

    trace_id = "7" * 32
    seen: list[str | None] = []

    async def handler(delivered: Envelope[BaseModel]) -> None:
        engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection, connection.begin():
                await record_consumed_event(
                    connection,
                    throwaway_schema,
                    delivered,
                    handler_result={"delivered": True},
                )
        finally:
            await engine.dispose()
        seen.append(get_trace_id())

    registry = HandlerRegistry()
    registry.register_payload_model("phase1.round_trip", RoundTripPayload)
    registry.register("phase1.round_trip", handler)

    token = set_trace_id(trace_id)
    try:
        asyncio.run(_publish(database_url, throwaway_schema, envelope))
    finally:
        reset_trace_id(token)

    # API -> outbox: the published row carries a W3C traceparent rooted at it.
    row = asyncio.run(_outbox_rows(database_url, throwaway_schema))[0]
    assert trace_id_from_traceparent(row["traceparent"]) == trace_id

    # outbox -> dispatcher: the claim restores it before the handler runs
    # (process_outbox_table binds the recovered id then fans out via dispatch).
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        result = asyncio.run(
            process_outbox_table(
                engine,
                OutboxTable(throwaway_schema, THROWAWAY_OUTBOX),
                registry,
                DispatcherConfig(),
            )
        )
    finally:
        asyncio.run(engine.dispose())

    assert result.deleted == 1
    assert asyncio.run(_ledger_rows(database_url, throwaway_schema)) == 1
    assert seen == [trace_id]


def test_row_without_request_context_uses_no_trace_id_on_the_worker_side(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    """A row written with no request context stays null and falls back to the
    event id as the worker-side correlation key (A1 behaviour, #695 keeps it).
    """
    asyncio.run(_materialize(database_url, throwaway_schema))

    envelope = Envelope[RoundTripPayload](
        event_id=uuid4(),
        event_type="phase1.round_trip",
        producer="phase1",
        payload=RoundTripPayload(round_trip_id=uuid4()),
    )

    seen: list[str | None] = []

    async def handler(delivered: Envelope[BaseModel]) -> None:
        engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection, connection.begin():
                await record_consumed_event(
                    connection,
                    throwaway_schema,
                    delivered,
                    handler_result={"delivered": True},
                )
        finally:
            await engine.dispose()
        seen.append(get_trace_id())

    registry = HandlerRegistry()
    registry.register_payload_model("phase1.round_trip", RoundTripPayload)
    registry.register("phase1.round_trip", handler)

    asyncio.run(_publish(database_url, throwaway_schema, envelope))

    row = asyncio.run(_outbox_rows(database_url, throwaway_schema))[0]
    assert row["traceparent"] is None

    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        result = asyncio.run(
            process_outbox_table(
                engine,
                OutboxTable(throwaway_schema, THROWAWAY_OUTBOX),
                registry,
                DispatcherConfig(),
            )
        )
    finally:
        asyncio.run(engine.dispose())

    assert result.deleted == 1
    assert asyncio.run(_ledger_rows(database_url, throwaway_schema)) == 1
    assert seen == [str(envelope.event_id)]
