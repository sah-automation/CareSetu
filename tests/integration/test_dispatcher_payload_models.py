"""Issue #943: the dispatcher reconstructs the fixed event types and drains them.

The bug: IAM and Partner did not register payload models for the events they
produce, so ``process_outbox_table`` logged "no payload model registered for
event_type" for every claimed row and left it inflight for reclaim, forever.
This test publishes REAL producer envelopes (the modules' own envelope
builders), builds the registry through the modules' real ``register_handlers``
(the composition-root seam), runs one poll pass, and asserts the dispatcher
reconstructs and fans out every row with no missing-model error. The three
event types have no handlers in a producer-only registry (their consumers live
in other modules), so a reconstructed row is fanned out and left inflight for
reclaim per the bus contract, and a non-reconstructed row would show
``fanned_out == 0`` plus the error log line instead. Skips cleanly when the
native PostgreSQL is unreachable, like the rest of the integration suite.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from bus.dispatcher import DispatcherConfig, OutboxTable, process_outbox_table
from bus.events import EVENT_OTP_SENT
from bus.outbox_ddl import materialize_consumed_events, materialize_outbox
from bus.outbox_writer import write_outbox
from bus.registry import HandlerRegistry
from modules.iam.adapters import register_handlers as iam_register_handlers
from modules.iam.domain.events import OtpSentPayload, otp_sent_envelope, patient_verified_envelope
from modules.partner.adapters import register_handlers as partner_register_handlers
from modules.partner.domain.events import directory_search_envelope

OUTBOX = "issue943_outbox"

PRODUCER_REGISTRY = HandlerRegistry()
iam_register_handlers(PRODUCER_REGISTRY)
partner_register_handlers(PRODUCER_REGISTRY)

ENVELOPES: tuple[Any, ...] = (
    otp_sent_envelope(
        identity_id=1,
        challenge_id=11,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    ),
    patient_verified_envelope(identity_id=2, phone_e164="+15550000002"),
    directory_search_envelope(
        patient_id=None,
        query="cardiologist",
        partner_type="clinic",
        specialty="cardiology",
        result_count=3,
        fell_back=False,
    ),
)


async def _materialize(database_url: str, schema: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await materialize_outbox(connection, schema, OUTBOX)
            await materialize_consumed_events(connection, schema)
    finally:
        await engine.dispose()


async def _publish(database_url: str, schema: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            for envelope in ENVELOPES:
                await write_outbox(connection, schema, OUTBOX, envelope)
    finally:
        await engine.dispose()


async def _outbox_states(database_url: str, schema: str) -> dict[str, list[str]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(f'SELECT event_type, status FROM "{schema}"."{OUTBOX}" ORDER BY event_type')
            )
            states: dict[str, list[str]] = {}
            for mapping in result.mappings().all():
                states.setdefault(str(mapping["event_type"]), []).append(str(mapping["status"]))
            return states
    finally:
        await engine.dispose()


def test_fixed_event_types_reconstruct_and_fan_out_without_missing_model_error(
    database_url: str, reachable_db: None, throwaway_schema: str, caplog: Any
) -> None:
    asyncio.run(_materialize(database_url, throwaway_schema))
    asyncio.run(_publish(database_url, throwaway_schema))

    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        with caplog.at_level(logging.ERROR, logger="bus.dispatcher"):
            result = asyncio.run(
                process_outbox_table(
                    engine,
                    OutboxTable(throwaway_schema, OUTBOX),
                    PRODUCER_REGISTRY,
                    DispatcherConfig(),
                )
            )
    finally:
        asyncio.run(engine.dispose())

    missing_model = [
        record for record in caplog.records if "no payload model registered" in record.getMessage()
    ]
    assert missing_model == []
    assert result.claimed == 3
    # All three rows reconstructed (payload_model_for hit) and dispatched to the
    # zero handlers a producer-only registry holds for them: an event type with
    # no subscribers drains as a successful delivery to all zero subscribers.
    assert result.fanned_out == 3
    assert result.deleted == 3
    states = asyncio.run(_outbox_states(database_url, throwaway_schema))
    assert states == {}


async def _publish_unvalidatable(database_url: str, schema: str) -> UUID:
    """Publish an ``otp.sent`` row whose stored payload cannot validate.

    The envelope is written normally, then the row's JSONB payload is replaced
    with a shape ``OtpSentPayload`` rejects - simulating a corrupt or legacy row
    whose reconstruction must fail at fan-out (issue #944).
    """
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            envelope = otp_sent_envelope(
                identity_id=1,
                challenge_id=11,
                expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
            await write_outbox(connection, schema, OUTBOX, envelope)
            await connection.execute(
                text(f'UPDATE "{schema}"."{OUTBOX}" SET payload = \'{{"unexpected": true}}\'')
            )
            return envelope.event_id
    finally:
        await engine.dispose()


async def _outbox_row_states(database_url: str, schema: str) -> list[dict[str, Any]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(f'SELECT event_type, status, attempts FROM "{schema}"."{OUTBOX}"')
            )
            return [dict(mapping) for mapping in result.mappings().all()]
    finally:
        await engine.dispose()


def test_row_with_an_unvalidatable_payload_is_dead_lettered_after_cap(
    database_url: str, reachable_db: None, throwaway_schema: str, caplog: Any
) -> None:
    """A payload that fails reconstruction is a permanent delivery failure.

    The reconstruction error rides the SAME failed-attempt path as a partial
    fan-out (issue #944): attempts increment with backoff and the row reaches
    ``dead_letter`` at ``max_attempts`` instead of looping inflight forever.
    """
    asyncio.run(_materialize(database_url, throwaway_schema))
    asyncio.run(_publish_unvalidatable(database_url, throwaway_schema))

    registry = HandlerRegistry()
    registry.register_payload_model(EVENT_OTP_SENT, OtpSentPayload)
    config = DispatcherConfig(backoff_base_seconds=0.0)

    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        with caplog.at_level(logging.ERROR, logger="bus.dispatcher"):
            results = []
            for _ in range(config.max_attempts + 1):
                result = asyncio.run(
                    process_outbox_table(
                        engine,
                        OutboxTable(throwaway_schema, OUTBOX),
                        registry,
                        config,
                    )
                )
                results.append(result)
                if result.dead_lettered:
                    break
    finally:
        asyncio.run(engine.dispose())

    assert sum(result.retried for result in results) == config.max_attempts - 1
    assert sum(result.dead_lettered for result in results) == 1
    rows = asyncio.run(_outbox_row_states(database_url, throwaway_schema))
    assert len(rows) == 1
    assert rows[0]["status"] == "dead_letter"
    assert rows[0]["attempts"] == config.max_attempts
    assert any("dead-lettered" in record.getMessage() for record in caplog.records)
