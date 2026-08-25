"""PHASE-3 T2: record shell + owner-only reads against real PostgreSQL (#211).

Proves the ticket's acceptance criteria on the native database:

1. Zero-setup ownership: a synthetic ``patient.registered`` row published into
   ``iam.iam_outbox`` flows through the REAL composition-root registry
   (``worker.main.build_registry``) and the dispatcher poll loop, creating the
   patient's empty record shell and the subscriber's ``consumed_events``
   ledger row; replaying the same ``event_id`` is a no-op (coding-standards
   §6 idempotency rule for every outbox consumer).
2. Facade-over-schema behaviour: idempotent ``create_record``, owner reads
   returning the documented typed timeline (empty on day zero), EVERY read
   attempt recorded in ``health_record_access_history`` - allowed and denied -
   and reverse-chronological entry ordering.

Requires the native PostgreSQL; the suite skips cleanly when it is
unreachable, migrates to head for the module and downgrades afterwards,
leaving the database as it was found.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from bus.dispatcher import DispatcherConfig, discover_outbox_tables, run_poll_loop
from bus.envelope import Envelope
from bus.outbox_writer import write_outbox
from modules.health.domain.events import PatientRegisteredPayload
from modules.health.domain.exceptions import (
    RecordAccessDeniedError,
    RecordNotFoundError,
)
from modules.health.facade import HealthFacade
from modules.iam.outbox import IAM_OUTBOX_TABLE
from worker.main import build_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_IDENTITY = 501
_PHONE = "+91987650001"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_schema(database_url: str) -> Iterator[None]:
    """Migrate to head (iam + health deltas) for the module, restore base after."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_tables(database_url: str, migrated_schema: None) -> AsyncIterator[None]:
    """Empty the health tables + iam outbox before every test."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE health.health_patient_records, "
                    "health.health_record_entries, health.health_record_access_history, "
                    "health.consumed_events, iam.iam_outbox CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


def _registered_envelope(
    identity_id: int, event_id: uuid.UUID | None = None
) -> Envelope[PatientRegisteredPayload]:
    return Envelope[PatientRegisteredPayload](
        event_id=event_id or uuid4(),
        event_type="patient.registered",
        producer="iam",
        payload=PatientRegisteredPayload(identity_id=identity_id, phone_e164=_PHONE),
    )


async def _publish(database_url: str, envelope: Envelope[PatientRegisteredPayload]) -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await write_outbox(connection, "iam", IAM_OUTBOX_TABLE, envelope)
    finally:
        await engine.dispose()


async def _query(database_url: str, sql: str) -> list[dict[str, Any]]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql))
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


async def _run_dispatcher_until(database_url: str, predicate_sql: str, expected: int) -> None:
    """Drive the real composition-root registry through the poll loop once."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        registry = build_registry()

        async def probe() -> int:
            async with engine.connect() as connection:
                count = await connection.scalar(text(predicate_sql))
            return int(count or 0)

        async def drive() -> None:
            async with engine.connect() as connection:
                tables = await discover_outbox_tables(connection, ("iam", "health"))
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
            for _ in range(200):
                if await probe() >= expected:
                    break
                await asyncio.sleep(0.05)
            stop_event.set()
            await task

        await drive()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_patient_registered_round_trip_creates_the_record_shell(
    database_url: str, clean_tables: None
) -> None:
    """AC1: registration creates the shell with no extra call - bus round-trip."""
    envelope = _registered_envelope(_IDENTITY)

    await _publish(database_url, envelope)
    await _run_dispatcher_until(
        database_url,
        "SELECT COUNT(*) FROM health.consumed_events",
        expected=1,
    )

    shells = await _query(
        database_url,
        f"SELECT identity_id FROM health.health_patient_records WHERE identity_id = {_IDENTITY}",
    )
    assert shells == [{"identity_id": _IDENTITY}]

    # The subscriber's ledger is the delivery record; delete-on-success means
    # the claimed iam row is gone after the full fan-out.
    ledger = await _query(
        database_url,
        "SELECT event_type, handler_result FROM health.consumed_events",
    )
    assert len(ledger) == 1
    assert ledger[0]["event_type"] == "patient.registered"
    remaining = await _query(database_url, "SELECT event_id FROM iam.iam_outbox")
    assert remaining == []


@pytest.mark.asyncio
async def test_replayed_event_id_is_a_no_op_for_shell_creation(
    database_url: str, clean_tables: None
) -> None:
    """Coding-standards §6: replay of the same ``event_id`` changes nothing."""
    envelope = _registered_envelope(_IDENTITY)

    await _publish(database_url, envelope)
    await _run_dispatcher_until(
        database_url, "SELECT COUNT(*) FROM health.consumed_events", expected=1
    )
    # Redelivery of the SAME event id (duplicate publish / reclaim race).
    await _publish(database_url, envelope)
    await _run_dispatcher_until(
        database_url, "SELECT COUNT(*) FROM health.consumed_events", expected=1
    )

    shells = await _query(
        database_url,
        f"SELECT COUNT(*) AS n FROM health.health_patient_records WHERE identity_id = {_IDENTITY}",
    )
    assert shells[0]["n"] == 1
    ledger_rows = await _query(database_url, "SELECT COUNT(*) AS n FROM health.consumed_events")
    assert ledger_rows[0]["n"] == 1


@pytest.mark.asyncio
async def test_create_record_is_idempotent(database_url: str, clean_tables: None) -> None:
    facade = HealthFacade(create_async_engine(database_url, poolclass=NullPool))

    first = await facade.create_record(_IDENTITY)
    second = await facade.create_record(_IDENTITY)

    assert first == second
    rows = await _query(
        database_url,
        "SELECT COUNT(*) AS n FROM health.health_patient_records",
    )
    assert rows[0]["n"] == 1


@pytest.mark.asyncio
async def test_owner_read_returns_empty_timeline_and_records_the_read(
    database_url: str, clean_tables: None
) -> None:
    """AC2: owner read of an empty timeline answers the documented contract."""
    facade = HealthFacade(create_async_engine(database_url, poolclass=NullPool))
    record_id = await facade.create_record(_IDENTITY)

    timeline = await facade.get_own_record(_IDENTITY)
    again = await facade.get_own_record(_IDENTITY)

    assert timeline.record_id == record_id
    assert timeline.patient_id == _IDENTITY
    assert timeline.entries == []
    # KPI-006 here: every read attempt lands in the ledger.
    accesses = await _query(
        database_url,
        "SELECT outcome, accessor_identity_id FROM health.health_record_access_history",
    )
    assert accesses == [
        {"outcome": "allowed", "accessor_identity_id": _IDENTITY},
        {"outcome": "allowed", "accessor_identity_id": _IDENTITY},
    ]
    assert again.entries == []


@pytest.mark.asyncio
async def test_non_owner_read_denied_and_recorded(database_url: str, clean_tables: None) -> None:
    """AC3: the denial leaves a named row in the access history ledger."""
    facade = HealthFacade(create_async_engine(database_url, poolclass=NullPool))
    record_id = await facade.create_record(_IDENTITY)
    intruder = 999

    with pytest.raises(RecordAccessDeniedError):
        await facade.get_record_as_owner(intruder, record_id)

    accesses = await _query(
        database_url,
        "SELECT outcome, accessor_identity_id FROM health.health_record_access_history",
    )
    assert accesses == [{"outcome": "denied", "accessor_identity_id": intruder}]


@pytest.mark.asyncio
async def test_unknown_record_answers_not_found_without_ledger_row(
    database_url: str, clean_tables: None
) -> None:
    facade = HealthFacade(create_async_engine(database_url, poolclass=NullPool))

    with pytest.raises(RecordNotFoundError):
        await facade.get_record_as_owner(_IDENTITY, 424242)

    accesses = await _query(
        database_url, "SELECT COUNT(*) AS n FROM health.health_record_access_history"
    )
    assert accesses[0]["n"] == 0


@pytest.mark.asyncio
async def test_timeline_orders_entries_reverse_chronologically(
    database_url: str, clean_tables: None
) -> None:
    facade = HealthFacade(create_async_engine(database_url, poolclass=NullPool))
    record_id = await facade.create_record(_IDENTITY)
    engine = create_async_engine(database_url, poolclass=NullPool)
    older = datetime.now(UTC) - timedelta(days=3)
    newer = datetime.now(UTC) - timedelta(hours=1)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO health.health_record_entries "
                    "(record_id, entry_type, payload, occurred_at) VALUES "
                    f"({record_id}, 'lab_report', '{{}}'::jsonb, :older), "
                    f"({record_id}, 'metric', '{{\"kind\": \"bp\"}}'::jsonb, :newer)"
                ),
                {"older": older, "newer": newer},
            )
    finally:
        await engine.dispose()

    timeline = await facade.get_own_record(_IDENTITY)

    assert [entry.entry_type for entry in timeline.entries] == ["metric", "lab_report"]
