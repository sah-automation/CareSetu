"""PHASE-3 T6: dormant record-entry consumers against real PostgreSQL (#215).

Proves the ticket's acceptance criteria on the native database:

1. Each of the four event names (``report.filed``, ``prescription.issued``,
   ``prescription.delivered``, ``settlement.recorded``) produces a correctly
   typed record entry in the patient timeline via the dispatcher.
2. Replaying the same ``event_id`` yields exactly one entry - no duplicates
   (round-trip harness pattern).
3. ``consent.granted/revoked`` update MOD-003's effective sharing state
   (consumed_events ledger records the delivery).

Uses throwaway outbox tables in the health schema (the consumer's schema)
following the round-trip harness pattern (test_round_trip.py).

Requires the native PostgreSQL; the suite skips cleanly when it is
unreachable, migrates to head for the module and downgrades afterwards,
leaving the database as it was found.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
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
from bus.outbox_ddl import materialize_consumed_events, materialize_outbox
from bus.outbox_writer import write_outbox
from modules.consent.domain.events import consent_granted_envelope, consent_revoked_envelope
from modules.health.domain.events import (
    PatientRegisteredPayload,
    PrescriptionDeliveredPayload,
    PrescriptionIssuedPayload,
    ReportFiledPayload,
    SettlementRecordedPayload,
)
from modules.health.facade import HEALTH_SCHEMA
from modules.iam.outbox import IAM_OUTBOX_TABLE
from worker.main import build_registry

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PATIENT = 801

# Throwaway outbox table names in the health schema (consumer's schema)
THROWAWAY_REPORT_FILED_OUTBOX = "t6_report_filed_outbox"
THROWAWAY_PRESCRIPTION_ISSUED_OUTBOX = "t6_prescription_issued_outbox"
THROWAWAY_PRESCRIPTION_DELIVERED_OUTBOX = "t6_prescription_delivered_outbox"
THROWAWAY_SETTLEMENT_RECORDED_OUTBOX = "t6_settlement_recorded_outbox"
THROWAWAY_CONSENT_GRANTED_OUTBOX = "t6_consent_granted_outbox"
THROWAWAY_CONSENT_REVOKED_OUTBOX = "t6_consent_revoked_outbox"

THROWAWAY_OUTBOX_TABLES = (
    THROWAWAY_REPORT_FILED_OUTBOX,
    THROWAWAY_PRESCRIPTION_ISSUED_OUTBOX,
    THROWAWAY_PRESCRIPTION_DELIVERED_OUTBOX,
    THROWAWAY_SETTLEMENT_RECORDED_OUTBOX,
    THROWAWAY_CONSENT_GRANTED_OUTBOX,
    THROWAWAY_CONSENT_REVOKED_OUTBOX,
)


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_schema(database_url: str) -> Iterator[None]:
    """Migrate to head (iam + health + consent deltas)."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_tables(database_url: str, migrated_schema: None) -> AsyncIterator[None]:
    """Empty the health tables before every test."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE health.health_patient_records, "
                    "health.health_record_entries, health.health_record_access_history, "
                    "health.consumed_events CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


async def _materialize_throwaway_outboxes(database_url: str) -> None:
    """Create throwaway outbox tables + consumed_events in health schema."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            for table_name in THROWAWAY_OUTBOX_TABLES:
                await materialize_outbox(connection, HEALTH_SCHEMA, table_name)
            await materialize_consumed_events(connection, HEALTH_SCHEMA)
    finally:
        await engine.dispose()


async def _drop_throwaway_outboxes(database_url: str) -> None:
    """Drop throwaway outbox tables from health schema."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            for table_name in THROWAWAY_OUTBOX_TABLES:
                await connection.execute(text(f'DROP TABLE IF EXISTS health."{table_name}"'))
    finally:
        await engine.dispose()


def _registered_envelope(
    identity_id: int, event_id: uuid.UUID | None = None
) -> Envelope[PatientRegisteredPayload]:
    return Envelope[PatientRegisteredPayload](
        event_id=event_id or uuid4(),
        event_type="patient.registered",
        producer="iam",
        payload=PatientRegisteredPayload(identity_id=identity_id, phone_e164="+91987650001"),
    )


def _report_filed_envelope(
    patient_id: int, event_id: uuid.UUID | None = None
) -> Envelope[ReportFiledPayload]:
    return Envelope[ReportFiledPayload](
        event_id=event_id or uuid4(),
        event_type="report.filed",
        producer="diagnostics",
        payload=ReportFiledPayload(
            order_id=1001,
            patient_id=patient_id,
            filename="report.pdf",
            occurred_at=datetime.now(UTC).isoformat(),
        ),
    )


def _prescription_issued_envelope(
    patient_id: int, event_id: uuid.UUID | None = None
) -> Envelope[PrescriptionIssuedPayload]:
    return Envelope[PrescriptionIssuedPayload](
        event_id=event_id or uuid4(),
        event_type="prescription.issued",
        producer="care",
        payload=PrescriptionIssuedPayload(
            prescription_id=2001,
            patient_id=patient_id,
            occurred_at=datetime.now(UTC).isoformat(),
        ),
    )


def _prescription_delivered_envelope(
    patient_id: int, event_id: uuid.UUID | None = None
) -> Envelope[PrescriptionDeliveredPayload]:
    return Envelope[PrescriptionDeliveredPayload](
        event_id=event_id or uuid4(),
        event_type="prescription.delivered",
        producer="fulfillment",
        payload=PrescriptionDeliveredPayload(
            fulfillment_order_id=3001,
            prescription_id=2001,
            patient_id=patient_id,
            occurred_at=datetime.now(UTC).isoformat(),
        ),
    )


def _settlement_recorded_envelope(
    patient_id: int, event_id: uuid.UUID | None = None
) -> Envelope[SettlementRecordedPayload]:
    return Envelope[SettlementRecordedPayload](
        event_id=event_id or uuid4(),
        event_type="settlement.recorded",
        producer="settlement",
        payload=SettlementRecordedPayload(
            settlement_id=4001,
            order_ref="ORDER-123",
            patient_id=patient_id,
            amount_paise=50000,
            occurred_at=datetime.now(UTC).isoformat(),
        ),
    )


async def _publish(database_url: str, outbox_table: str, envelope: Envelope[Any]) -> None:
    """Publish envelope to a throwaway outbox in the health schema."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await write_outbox(connection, HEALTH_SCHEMA, outbox_table, envelope)
    finally:
        await engine.dispose()


async def _publish_to_iam(database_url: str, outbox_table: str, envelope: Envelope[Any]) -> None:
    """Publish to iam.iam_outbox."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await write_outbox(connection, "iam", outbox_table, envelope)
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


async def _ensure_record_shell(database_url: str, patient_id: int) -> int:
    """Ensure record shell exists by publishing patient.registered and running dispatcher."""
    reg_env = _registered_envelope(patient_id)
    await _publish_to_iam(database_url, IAM_OUTBOX_TABLE, reg_env)
    await _run_dispatcher_until(
        database_url,
        "SELECT COUNT(*) FROM health.consumed_events WHERE event_type = 'patient.registered'",
        expected=1,
    )
    # Get the record_id
    record = await _query(
        database_url,
        f"SELECT id FROM health.health_patient_records WHERE identity_id = {patient_id}",
    )
    return record[0]["id"]


async def _run_test_with_throwaway_outboxes(database_url: str, test_fn, *args, **kwargs) -> None:
    """Run a test with throwaway outboxes materialized, then cleaned up."""
    await _materialize_throwaway_outboxes(database_url)
    try:
        await test_fn(database_url, *args, **kwargs)
    finally:
        await _drop_throwaway_outboxes(database_url)


@pytest.mark.asyncio
async def test_report_filed_creates_lab_report_entry(database_url: str, clean_tables: None) -> None:
    """AC: report.filed produces a lab_report entry in the timeline."""

    async def _test(db_url: str) -> None:
        record_id = await _ensure_record_shell(db_url, _PATIENT)

        env = _report_filed_envelope(_PATIENT)
        await _publish(db_url, THROWAWAY_REPORT_FILED_OUTBOX, env)
        await _run_dispatcher_until(
            db_url,
            "SELECT COUNT(*) FROM health.consumed_events WHERE event_type = 'report.filed'",
            expected=1,
        )

        entries = await _query(
            db_url,
            "SELECT entry_type, payload FROM health.health_record_entries "
            f"WHERE record_id = {record_id}",
        )
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "lab_report"
        assert entries[0]["payload"]["order_id"] == 1001
        assert entries[0]["payload"]["filename"] == "report.pdf"

    await _run_test_with_throwaway_outboxes(database_url, _test)


@pytest.mark.asyncio
async def test_prescription_issued_creates_prescription_entry(
    database_url: str, clean_tables: None
) -> None:
    """AC: prescription.issued produces a prescription entry in the timeline."""

    async def _test(db_url: str) -> None:
        record_id = await _ensure_record_shell(db_url, _PATIENT)

        env = _prescription_issued_envelope(_PATIENT)
        await _publish(db_url, THROWAWAY_PRESCRIPTION_ISSUED_OUTBOX, env)
        await _run_dispatcher_until(
            db_url,
            (
                "SELECT COUNT(*) FROM health.consumed_events "
                "WHERE event_type = 'prescription.issued'"
            ),
            expected=1,
        )

        entries = await _query(
            db_url,
            (
                "SELECT entry_type, payload FROM health.health_record_entries "
                f"WHERE record_id = {record_id}"
            ),
        )
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "prescription"
        assert entries[0]["payload"]["prescription_id"] == 2001
        assert entries[0]["payload"]["status"] == "issued"

    await _run_test_with_throwaway_outboxes(database_url, _test)


@pytest.mark.asyncio
async def test_prescription_delivered_creates_prescription_entry(
    database_url: str, clean_tables: None
) -> None:
    """AC: prescription.delivered produces a prescription entry in the timeline."""

    async def _test(db_url: str) -> None:
        record_id = await _ensure_record_shell(db_url, _PATIENT)

        env = _prescription_delivered_envelope(_PATIENT)
        await _publish(db_url, THROWAWAY_PRESCRIPTION_DELIVERED_OUTBOX, env)
        await _run_dispatcher_until(
            db_url,
            (
                "SELECT COUNT(*) FROM health.consumed_events "
                "WHERE event_type = 'prescription.delivered'"
            ),
            expected=1,
        )

        entries = await _query(
            db_url,
            (
                "SELECT entry_type, payload FROM health.health_record_entries "
                f"WHERE record_id = {record_id}"
            ),
        )
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "prescription"
        assert entries[0]["payload"]["fulfillment_order_id"] == 3001
        assert entries[0]["payload"]["prescription_id"] == 2001
        assert entries[0]["payload"]["status"] == "delivered"

    await _run_test_with_throwaway_outboxes(database_url, _test)


@pytest.mark.asyncio
async def test_settlement_recorded_creates_settlement_entry(
    database_url: str, clean_tables: None
) -> None:
    """AC: settlement.recorded produces a settlement entry in the timeline."""

    async def _test(db_url: str) -> None:
        record_id = await _ensure_record_shell(db_url, _PATIENT)

        env = _settlement_recorded_envelope(_PATIENT)
        await _publish(db_url, THROWAWAY_SETTLEMENT_RECORDED_OUTBOX, env)
        await _run_dispatcher_until(
            db_url,
            (
                "SELECT COUNT(*) FROM health.consumed_events "
                "WHERE event_type = 'settlement.recorded'"
            ),
            expected=1,
        )

        entries = await _query(
            db_url,
            (
                "SELECT entry_type, payload FROM health.health_record_entries "
                f"WHERE record_id = {record_id}"
            ),
        )
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "settlement"
        assert entries[0]["payload"]["settlement_id"] == 4001
        assert entries[0]["payload"]["order_ref"] == "ORDER-123"
        assert entries[0]["payload"]["amount_paise"] == 50000

    await _run_test_with_throwaway_outboxes(database_url, _test)


@pytest.mark.asyncio
async def test_replayed_report_filed_is_no_op(database_url: str, clean_tables: None) -> None:
    """AC: Replay of the same event_id is a no-op (dedupe via consumed_events ledger)."""

    async def _test(db_url: str) -> None:
        record_id = await _ensure_record_shell(db_url, _PATIENT)

        fixed_event_id = uuid4()
        env = _report_filed_envelope(_PATIENT, event_id=fixed_event_id)

        await _publish(db_url, THROWAWAY_REPORT_FILED_OUTBOX, env)
        await _run_dispatcher_until(
            db_url,
            "SELECT COUNT(*) FROM health.consumed_events WHERE event_type = 'report.filed'",
            expected=1,
        )

        await _publish(db_url, THROWAWAY_REPORT_FILED_OUTBOX, env)
        await _run_dispatcher_until(
            db_url,
            "SELECT COUNT(*) FROM health.consumed_events WHERE event_type = 'report.filed'",
            expected=1,
        )

        entries = await _query(
            db_url,
            f"SELECT COUNT(*) AS n FROM health.health_record_entries WHERE record_id = {record_id}",
        )
        assert entries[0]["n"] == 1

        ledger_rows = await _query(
            db_url,
            "SELECT COUNT(*) AS n FROM health.consumed_events WHERE event_type = 'report.filed'",
        )
        assert ledger_rows[0]["n"] == 1

    await _run_test_with_throwaway_outboxes(database_url, _test)


@pytest.mark.asyncio
async def test_replayed_prescription_issued_is_no_op(database_url: str, clean_tables: None) -> None:
    """AC: Replay of prescription.issued is a no-op."""

    async def _test(db_url: str) -> None:
        record_id = await _ensure_record_shell(db_url, _PATIENT)

        fixed_event_id = uuid4()
        env = _prescription_issued_envelope(_PATIENT, event_id=fixed_event_id)

        await _publish(db_url, THROWAWAY_PRESCRIPTION_ISSUED_OUTBOX, env)
        await _run_dispatcher_until(
            db_url,
            "SELECT COUNT(*) FROM health.consumed_events WHERE event_type = 'prescription.issued'",
            expected=1,
        )

        await _publish(db_url, THROWAWAY_PRESCRIPTION_ISSUED_OUTBOX, env)
        await _run_dispatcher_until(
            db_url,
            "SELECT COUNT(*) FROM health.consumed_events WHERE event_type = 'prescription.issued'",
            expected=1,
        )

        entries = await _query(
            db_url,
            f"SELECT COUNT(*) AS n FROM health.health_record_entries WHERE record_id = {record_id}",
        )
        assert entries[0]["n"] == 1

    await _run_test_with_throwaway_outboxes(database_url, _test)


@pytest.mark.asyncio
async def test_consent_granted_records_in_consumed_events(
    database_url: str, clean_tables: None
) -> None:
    """AC: consent.granted updates effective sharing state (recorded in consumed_events)."""

    async def _test(db_url: str) -> None:
        await _ensure_record_shell(db_url, _PATIENT)

        env = consent_granted_envelope(
            consent_id=1,
            lineage_ref="C-2024-001",
            patient_id=_PATIENT,
            counterparty_type="doctor",
            counterparty_id="dr-1",
            record_scope="consultations",
            version=1,
        )
        await _publish(db_url, THROWAWAY_CONSENT_GRANTED_OUTBOX, env)
        await _run_dispatcher_until(
            db_url,
            ("SELECT COUNT(*) FROM health.consumed_events WHERE event_type = 'consent.granted'"),
            expected=1,
        )

        ledger = await _query(
            db_url,
            (
                "SELECT event_type, handler_result FROM health.consumed_events "
                "WHERE event_type = 'consent.granted'"
            ),
        )
        assert len(ledger) == 1
        assert ledger[0]["event_type"] == "consent.granted"
        assert ledger[0]["handler_result"]["handler"] == "handle_consent_granted"

    await _run_test_with_throwaway_outboxes(database_url, _test)


@pytest.mark.asyncio
async def test_consent_revoked_records_in_consumed_events(
    database_url: str, clean_tables: None
) -> None:
    """AC: consent.revoked updates effective sharing state (recorded in consumed_events)."""

    async def _test(db_url: str) -> None:
        await _ensure_record_shell(db_url, _PATIENT)

        env = consent_revoked_envelope(
            consent_id=1,
            lineage_ref="C-2024-001",
            patient_id=_PATIENT,
            counterparty_type="doctor",
            counterparty_id="dr-1",
            record_scope="consultations",
            version=1,
        )
        await _publish(db_url, THROWAWAY_CONSENT_REVOKED_OUTBOX, env)
        await _run_dispatcher_until(
            db_url,
            ("SELECT COUNT(*) FROM health.consumed_events WHERE event_type = 'consent.revoked'"),
            expected=1,
        )

        ledger = await _query(
            db_url,
            (
                "SELECT event_type, handler_result FROM health.consumed_events "
                "WHERE event_type = 'consent.revoked'"
            ),
        )
        assert len(ledger) == 1
        assert ledger[0]["event_type"] == "consent.revoked"
        assert ledger[0]["handler_result"]["handler"] == "handle_consent_revoked"

    await _run_test_with_throwaway_outboxes(database_url, _test)
