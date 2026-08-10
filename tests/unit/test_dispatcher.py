"""PHASE-1 T3a: dispatcher poll-loop pure contracts (ticket #22).

Pins the database-free parts of the poll loop: reconstructing a typed
``Envelope`` from an outbox row (row contract carries no ``producer``/
``schema_version``; the JSONB payload is validated into the registered payload
model, never passed as a raw dict) and the poll loop's stop semantics. The
claim/reclaim/delete SQL and the drain behaviour are exercised against the
native PostgreSQL in ``tests/integration/test_dispatcher.py``.
"""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine

from bus.dispatcher import (
    DispatcherConfig,
    OutboxRow,
    OutboxTable,
    envelope_from_row,
    run_poll_loop,
)
from bus.registry import HandlerRegistry


class RoundTripPayload(BaseModel):
    round_trip_id: UUID


def _row() -> OutboxRow:
    return OutboxRow(
        id=uuid4(),
        event_id=uuid4(),
        event_type="phase1.round_trip",
        payload={"round_trip_id": str(uuid4())},
        occurred_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
        next_attempt_at=datetime(2026, 8, 11, 12, 1, tzinfo=UTC),
    )


def test_envelope_from_row_validates_payload_into_the_registered_model() -> None:
    row = _row()

    envelope = envelope_from_row(row, "t_throwaway", RoundTripPayload)

    assert envelope.event_id == row.event_id
    assert envelope.event_type == "phase1.round_trip"
    assert envelope.occurred_at == row.occurred_at
    assert isinstance(envelope.payload, RoundTripPayload)
    assert envelope.payload.round_trip_id == UUID(row.payload["round_trip_id"])


def test_envelope_from_row_infers_producer_from_the_outbox_schema() -> None:
    envelope = envelope_from_row(_row(), "t_throwaway", RoundTripPayload)

    assert envelope.producer == "t_throwaway"


def test_envelope_from_row_keeps_schema_version_default() -> None:
    envelope = envelope_from_row(_row(), "t_throwaway", RoundTripPayload)

    assert envelope.schema_version == 1


def test_run_poll_loop_returns_immediately_when_stop_event_is_set() -> None:
    engine = create_async_engine("postgresql+asyncpg://caresetu:caresetu@localhost:5432/caresetu")
    stop_event = asyncio.Event()
    stop_event.set()

    asyncio.run(
        run_poll_loop(
            engine,
            [OutboxTable("t_throwaway", "t3a_outbox")],
            HandlerRegistry(),
            DispatcherConfig(poll_interval_seconds=0.01),
            stop_event=stop_event,
        )
    )
