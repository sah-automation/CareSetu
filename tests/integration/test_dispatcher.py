"""PHASE-1 T3a/T3b: dispatcher poll loop against the native PostgreSQL (tickets #22, #23).

Proves the poll loop's external behaviour (issue #16, ADR-0002 §2) against a
throwaway schema/outbox materialized through the Phase 1 helper: pending rows
are durably claimed ``inflight`` then deleted after a full successful fan-out,
stale ``inflight`` rows are reclaimed after the claim timeout, a partial
fan-out schedules an exponential-backoff retry and dead-letters once the 5-attempt
cap is reached while a healthy sibling subscriber still receives the event,
outbox tables are discovered by list rather than hardcoded modules, and the
dispatcher touches outbox tables only - never domain tables. Runs against the
local native PostgreSQL and skips cleanly when it is unreachable, like the rest
of the integration suite.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from bus.dispatcher import (
    DispatcherConfig,
    OutboxTable,
    discover_outbox_tables,
    process_outbox_table,
    run_poll_loop,
)
from bus.envelope import Envelope
from bus.ledger import record_consumed_event
from bus.outbox_ddl import materialize_consumed_events, materialize_outbox
from bus.outbox_writer import write_outbox
from bus.registry import Handler, HandlerRegistry

THROWAWAY_OUTBOX = "t3a_outbox"
DOMAIN_TABLE = "t3a_domain_patients"

CONFIG = DispatcherConfig()
MAX_ATTEMPTS = CONFIG.max_attempts
POLL_TIMES_UP_TO_CAP = MAX_ATTEMPTS + 1


class RoundTripPayload(BaseModel):
    round_trip_id: UUID


async def _materialize(database_url: str, schema: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await materialize_outbox(connection, schema, THROWAWAY_OUTBOX)
            await materialize_consumed_events(connection, schema)
            await connection.execute(
                text(
                    f'CREATE TABLE "{schema}"."{DOMAIN_TABLE}" (id INTEGER PRIMARY KEY, name TEXT)'
                )
            )
            await connection.execute(
                text(f'INSERT INTO "{schema}"."{DOMAIN_TABLE}" (id, name) VALUES (1, \'patient\')')
            )
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
                text(
                    f"SELECT id, event_id, status, attempts, next_attempt_at "
                    f'FROM "{schema}"."{THROWAWAY_OUTBOX}"'
                )
            )
            return [dict(mapping) for mapping in result.mappings().all()]
    finally:
        await engine.dispose()


async def _ledger_count(database_url: str, schema: str) -> int:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            count = await connection.scalar(
                text(f'SELECT COUNT(*) FROM "{schema}".consumed_events')
            )
            return int(count or 0)
    finally:
        await engine.dispose()


async def _domain_rows(database_url: str, schema: str) -> list[dict[str, Any]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(f'SELECT id, name FROM "{schema}"."{DOMAIN_TABLE}"')
            )
            return [dict(mapping) for mapping in result.mappings().all()]
    finally:
        await engine.dispose()


async def _set_inflight(
    database_url: str, schema: str, event_id: UUID, seconds_offset: int
) -> None:
    """Force the row to ``inflight`` as if a worker claimed it ``seconds_offset`` ago."""
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    f'UPDATE "{schema}"."{THROWAWAY_OUTBOX}" '
                    "SET status = 'inflight', "
                    "next_attempt_at = now() + make_interval(secs => :offset) "
                    "WHERE event_id = :event_id"
                ),
                {"offset": seconds_offset, "event_id": event_id},
            )
    finally:
        await engine.dispose()


def _idempotent_subscriber(database_url: str, schema: str) -> Handler:
    """A subscriber that records its ledger row in its own processing transaction."""

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


def _failing_subscriber() -> Handler:
    async def handler(envelope: Envelope[BaseModel]) -> None:
        raise RuntimeError("boom")

    return handler


def _registry(database_url: str, schema: str, handler: Handler) -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register_payload_model("phase1.round_trip", RoundTripPayload)
    registry.register("phase1.round_trip", handler)
    return registry


def _idempotent_registry(database_url: str, schema: str) -> HandlerRegistry:
    return _registry(database_url, schema, _idempotent_subscriber(database_url, schema))


def _poll(database_url: str, schema: str, registry: HandlerRegistry) -> Any:
    return _poll_with(database_url, schema, registry, CONFIG)


def _poll_with(
    database_url: str,
    schema: str,
    registry: HandlerRegistry,
    config: DispatcherConfig,
) -> Any:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        return asyncio.run(
            process_outbox_table(
                engine,
                OutboxTable(schema, THROWAWAY_OUTBOX),
                registry,
                config,
            )
        )
    finally:
        asyncio.run(engine.dispose())


def _envelope() -> Envelope[RoundTripPayload]:
    return Envelope[RoundTripPayload](
        event_id=uuid4(),
        event_type="phase1.round_trip",
        producer="phase1",
        payload=RoundTripPayload(round_trip_id=uuid4()),
    )


def test_poll_drains_pending_rows_and_deletes_after_fan_out(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))
    first, second = _envelope(), _envelope()
    asyncio.run(_publish(database_url, throwaway_schema, first))
    asyncio.run(_publish(database_url, throwaway_schema, second))

    result = _poll(
        database_url,
        throwaway_schema,
        _idempotent_registry(database_url, throwaway_schema),
    )

    assert result.stale_reclaimed == 0
    assert result.claimed == 2
    assert result.fanned_out == 2
    assert result.deleted == 2
    assert asyncio.run(_outbox_rows(database_url, throwaway_schema)) == []
    assert asyncio.run(_ledger_count(database_url, throwaway_schema)) == 2


def test_stale_inflight_row_is_reclaimed_and_processed(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))
    envelope = _envelope()
    asyncio.run(_publish(database_url, throwaway_schema, envelope))
    asyncio.run(
        _set_inflight(database_url, throwaway_schema, envelope.event_id, seconds_offset=-3600)
    )

    result = _poll(
        database_url,
        throwaway_schema,
        _idempotent_registry(database_url, throwaway_schema),
    )

    assert result.stale_reclaimed == 1
    assert result.claimed == 1
    assert result.deleted == 1
    assert asyncio.run(_outbox_rows(database_url, throwaway_schema)) == []
    assert asyncio.run(_ledger_count(database_url, throwaway_schema)) == 1


def test_fresh_inflight_row_is_not_reclaimed(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))
    envelope = _envelope()
    asyncio.run(_publish(database_url, throwaway_schema, envelope))
    asyncio.run(
        _set_inflight(database_url, throwaway_schema, envelope.event_id, seconds_offset=3600)
    )

    result = _poll(
        database_url,
        throwaway_schema,
        _idempotent_registry(database_url, throwaway_schema),
    )

    assert result.stale_reclaimed == 0
    assert result.claimed == 0
    rows = asyncio.run(_outbox_rows(database_url, throwaway_schema))
    assert len(rows) == 1
    assert rows[0]["status"] == "inflight"
    assert rows[0]["next_attempt_at"] is not None


def test_partial_failure_schedules_backoff_retry_not_delete(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))
    envelope = _envelope()
    asyncio.run(_publish(database_url, throwaway_schema, envelope))

    result = _poll(
        database_url,
        throwaway_schema,
        _registry(database_url, throwaway_schema, _failing_subscriber()),
    )

    assert result.claimed == 1
    assert result.fanned_out == 1
    assert result.deleted == 0
    assert result.retried == 1
    assert result.dead_lettered == 0
    rows = asyncio.run(_outbox_rows(database_url, throwaway_schema))
    assert len(rows) == 1
    assert rows[0]["event_id"] == envelope.event_id
    assert rows[0]["status"] == "pending"
    assert rows[0]["attempts"] == 1
    assert rows[0]["next_attempt_at"] > datetime.now(UTC)


def _poll_times(
    database_url: str,
    schema: str,
    registry: HandlerRegistry,
    times: int,
    config: DispatcherConfig,
) -> list[Any]:
    results = []
    for _ in range(times):
        result = _poll_with(database_url, schema, registry, config)
        results.append(result)
        if result.dead_lettered:
            break
    return results


def test_failing_subscriber_retries_then_dead_letters_after_cap(
    database_url: str,
    reachable_db: None,
    throwaway_schema: str,
    caplog: Any,
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))
    envelope = _envelope()
    asyncio.run(_publish(database_url, throwaway_schema, envelope))
    config = DispatcherConfig(backoff_base_seconds=0.0)

    with caplog.at_level(logging.ERROR, logger="bus.dispatcher"):
        results = _poll_times(
            database_url,
            throwaway_schema,
            _registry(database_url, throwaway_schema, _failing_subscriber()),
            times=POLL_TIMES_UP_TO_CAP,
            config=config,
        )

    retried = sum(result.retried for result in results)
    dead_lettered = sum(result.dead_lettered for result in results)
    assert retried == 4
    assert dead_lettered == 1
    rows = asyncio.run(_outbox_rows(database_url, throwaway_schema))
    assert len(rows) == 1
    assert rows[0]["status"] == "dead_letter"
    assert rows[0]["attempts"] == 5
    assert any("dead-lettered" in record.getMessage() for record in caplog.records)


def test_failing_subscriber_does_not_block_healthy_sibling(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))
    envelope = _envelope()
    asyncio.run(_publish(database_url, throwaway_schema, envelope))
    config = DispatcherConfig(backoff_base_seconds=0.0)
    registry = HandlerRegistry()
    registry.register_payload_model("phase1.round_trip", RoundTripPayload)
    registry.register("phase1.round_trip", _failing_subscriber())
    registry.register(
        "phase1.round_trip",
        _idempotent_subscriber(database_url, throwaway_schema),
    )

    results = _poll_times(
        database_url,
        throwaway_schema,
        registry,
        times=POLL_TIMES_UP_TO_CAP,
        config=config,
    )

    assert sum(result.retried for result in results) == 4
    assert sum(result.dead_lettered for result in results) == 1
    assert asyncio.run(_ledger_count(database_url, throwaway_schema)) == 1
    rows = asyncio.run(_outbox_rows(database_url, throwaway_schema))
    assert len(rows) == 1
    assert rows[0]["status"] == "dead_letter"
    assert rows[0]["attempts"] == 5


def test_healthy_subscriber_success_independent_of_failing_sibling(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))
    envelope = _envelope()
    asyncio.run(_publish(database_url, throwaway_schema, envelope))
    registry = HandlerRegistry()
    registry.register_payload_model("phase1.round_trip", RoundTripPayload)
    registry.register(
        "phase1.round_trip",
        _idempotent_subscriber(database_url, throwaway_schema),
    )
    registry.register("phase1.round_trip", _failing_subscriber())

    result = _poll(
        database_url,
        throwaway_schema,
        registry,
    )

    assert result.fanned_out == 1
    assert result.deleted == 0
    assert result.retried == 1
    assert asyncio.run(_ledger_count(database_url, throwaway_schema)) == 1
    rows = asyncio.run(_outbox_rows(database_url, throwaway_schema))
    assert rows[0]["attempts"] == 1


def test_dead_lettered_row_is_not_claimed_again(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))
    envelope = _envelope()
    asyncio.run(_publish(database_url, throwaway_schema, envelope))
    config = DispatcherConfig(backoff_base_seconds=0.0)
    _poll_times(
        database_url,
        throwaway_schema,
        _registry(database_url, throwaway_schema, _failing_subscriber()),
        times=POLL_TIMES_UP_TO_CAP,
        config=config,
    )

    result = _poll(
        database_url,
        throwaway_schema,
        _registry(database_url, throwaway_schema, _failing_subscriber()),
    )

    assert result.claimed == 0
    assert result.fanned_out == 0
    assert result.deleted == 0
    rows = asyncio.run(_outbox_rows(database_url, throwaway_schema))
    assert len(rows) == 1
    assert rows[0]["status"] == "dead_letter"


def test_row_without_registered_payload_model_is_left_for_reclaim(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))
    envelope = _envelope()
    asyncio.run(_publish(database_url, throwaway_schema, envelope))

    registry = HandlerRegistry()
    registry.register("phase1.round_trip", _idempotent_subscriber(database_url, throwaway_schema))

    result = _poll(database_url, throwaway_schema, registry)

    assert result.claimed == 1
    assert result.fanned_out == 0
    assert result.deleted == 0
    rows = asyncio.run(_outbox_rows(database_url, throwaway_schema))
    assert len(rows) == 1
    assert rows[0]["status"] == "inflight"
    assert asyncio.run(_ledger_count(database_url, throwaway_schema)) == 0


def test_row_with_no_registered_handlers_is_left_for_reclaim_not_deleted(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))
    envelope = _envelope()
    asyncio.run(_publish(database_url, throwaway_schema, envelope))

    registry = HandlerRegistry()
    registry.register_payload_model("phase1.round_trip", RoundTripPayload)

    result = _poll(database_url, throwaway_schema, registry)

    assert result.claimed == 1
    assert result.fanned_out == 1
    assert result.deleted == 0
    rows = asyncio.run(_outbox_rows(database_url, throwaway_schema))
    assert len(rows) == 1
    assert rows[0]["status"] == "inflight"
    assert asyncio.run(_ledger_count(database_url, throwaway_schema)) == 0


async def _discover(database_url: str, schemas: list[str]) -> tuple[OutboxTable, ...]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return await discover_outbox_tables(connection, schemas)
    finally:
        await engine.dispose()


def test_discover_outbox_tables_lists_outbox_tables_only(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))

    tables = asyncio.run(_discover(database_url, [throwaway_schema]))

    assert tables == (OutboxTable(throwaway_schema, THROWAWAY_OUTBOX),)


def test_discover_outbox_tables_with_no_schemas_is_empty(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    tables = asyncio.run(_discover(database_url, []))
    assert tables == ()


def test_dispatcher_touches_outbox_tables_only(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))
    envelope = _envelope()
    asyncio.run(_publish(database_url, throwaway_schema, envelope))

    result = _poll(
        database_url,
        throwaway_schema,
        _idempotent_registry(database_url, throwaway_schema),
    )

    assert result.deleted == 1
    assert asyncio.run(_outbox_rows(database_url, throwaway_schema)) == []
    assert asyncio.run(_ledger_count(database_url, throwaway_schema)) == 1
    assert asyncio.run(_domain_rows(database_url, throwaway_schema)) == [
        {"id": 1, "name": "patient"}
    ]


def test_run_poll_loop_drains_discovered_outbox_tables(
    database_url: str, reachable_db: None, throwaway_schema: str
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))
    envelope = _envelope()
    asyncio.run(_publish(database_url, throwaway_schema, envelope))
    registry = _idempotent_registry(database_url, throwaway_schema)
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)

    async def drive() -> tuple[OutboxTable, ...]:
        async with engine.connect() as connection:
            tables = await discover_outbox_tables(connection, [throwaway_schema])
        stop_event = asyncio.Event()
        task = asyncio.create_task(
            run_poll_loop(
                engine,
                tables,
                registry,
                DispatcherConfig(poll_interval_seconds=0.05),
                stop_event=stop_event,
            )
        )
        for _ in range(100):
            async with engine.connect() as connection:
                count = await connection.scalar(
                    text(f'SELECT COUNT(*) FROM "{throwaway_schema}".consumed_events')
                )
            if int(count or 0) == 1:
                break
            await asyncio.sleep(0.05)
        stop_event.set()
        await task
        return tables

    try:
        tables = asyncio.run(drive())
    finally:
        asyncio.run(engine.dispose())

    assert tables == (OutboxTable(throwaway_schema, THROWAWAY_OUTBOX),)
    assert asyncio.run(_outbox_rows(database_url, throwaway_schema)) == []
    assert asyncio.run(_ledger_count(database_url, throwaway_schema)) == 1
