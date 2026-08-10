"""PHASE-1 T3a/T3b: dispatcher poll-loop pure contracts (tickets #22, #23).

Pins the database-free parts of the poll loop: reconstructing a typed
``Envelope`` from an outbox row (row contract carries no ``producer``/
``schema_version``; the JSONB payload is validated into the registered payload
model, never passed as a raw dict), the poll loop's stop semantics, and the
T3b retry/dead-letter helpers (exponential-backoff delay and the
pending-vs-dead-letter decision at the ``max_attempts`` cap). The
claim/reclaim/delete/retry SQL and the drain behaviour are exercised against
the native PostgreSQL in ``tests/integration/test_dispatcher.py``.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import create_async_engine

from bus.dispatcher import (
    DispatcherConfig,
    OutboxRow,
    OutboxTable,
    backoff_delay,
    envelope_from_row,
    retry_status_after_failure,
    run_poll_loop,
)
from bus.outbox_ddl import OUTBOX_STATUS_DEAD_LETTER, OUTBOX_STATUS_PENDING
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
        attempts=0,
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


def test_backoff_delay_doubles_exponentially_with_each_attempt() -> None:
    config = DispatcherConfig(backoff_base_seconds=2.0)

    assert backoff_delay(1, config) == timedelta(seconds=2)
    assert backoff_delay(2, config) == timedelta(seconds=4)
    assert backoff_delay(3, config) == timedelta(seconds=8)
    assert backoff_delay(4, config) == timedelta(seconds=16)


def test_backoff_delay_with_zero_base_is_immediate() -> None:
    config = DispatcherConfig(backoff_base_seconds=0.0)

    assert backoff_delay(1, config) == timedelta(seconds=0)
    assert backoff_delay(5, config) == timedelta(seconds=0)


def test_retry_status_below_cap_is_pending() -> None:
    config = DispatcherConfig(max_attempts=5)

    for attempt in range(1, 5):
        assert retry_status_after_failure(attempt, config) == OUTBOX_STATUS_PENDING


def test_retry_status_at_cap_is_dead_letter() -> None:
    config = DispatcherConfig(max_attempts=5)

    assert retry_status_after_failure(5, config) == OUTBOX_STATUS_DEAD_LETTER
    assert retry_status_after_failure(6, config) == OUTBOX_STATUS_DEAD_LETTER


def test_retry_status_respects_custom_cap() -> None:
    config = DispatcherConfig(max_attempts=3)

    assert retry_status_after_failure(2, config) == OUTBOX_STATUS_PENDING
    assert retry_status_after_failure(3, config) == OUTBOX_STATUS_DEAD_LETTER
