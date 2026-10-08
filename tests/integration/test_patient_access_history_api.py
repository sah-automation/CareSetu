"""PHASE-4 T7 + #665: patient access-history view against real PostgreSQL (#241, FEAT-003).

Proves the ticket's acceptance criteria on the native database:

1. Owner reads (the plain own-record read and the allowed addressed read)
   write NO ``health_record_access_history`` row and NO outbox envelope - the
   ledger answers only "who ELSE has seen this record".
2. Counterparty rows (doctor console views) and the addressed read's DENIED
   path are recorded, returned newest first as typed ``AccessHistoryEntry``
   values: ``actor_id`` / ``actor_type`` / ``scope`` / ``accessed_at`` /
   ``denied`` / ``denial_reason`` (v3.1 enrichment columns written by
   ``_log_access``).
3. A pre-existing self row is invisible at read time (the both-columns
   read filter) even against a database the purge migration has not touched,
   while a cross-patient denied row survives; the purge migration itself
   deletes stored self rows and retains cross-patient denied rows.
4. The empty case answers an empty list, not an error.
5. ``AuditFacade.get_access_history`` delegates to the MOD-003 facade through
   the cross-module seam.

Requires the native PostgreSQL; the suite skips cleanly when it is
unreachable, migrates to head for the module and downgrades afterwards,
leaving the database as it was found.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from modules.audit.facade import AuditFacade
from modules.health.domain.exceptions import RecordAccessDeniedError
from modules.health.facade import HealthFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

# Parent of the v8.18 purge migration: the purge test round-trips through
# this revision to re-run the DELETE against rows inserted at head.
_PRE_PURGE_REVISION = "3e7c5a1d8f24"

_IDENTITY = 601
_INTRUDER = 999
_DOCTOR = 11


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_schema(database_url: str) -> Iterator[None]:
    """Migrate to head (health + audit deltas incl. v3.1), restore base after."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_tables(database_url: str, migrated_schema: None) -> AsyncIterator[None]:
    """Empty the health tables + outboxes before every test."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE health.health_patient_records, "
                    "health.health_record_entries, health.health_record_access_history, "
                    "health.consumed_events, health.health_outbox, iam.iam_outbox CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


def _health_facade(database_url: str) -> HealthFacade:
    return HealthFacade(create_async_engine(database_url, poolclass=NullPool))


async def _count(database_url: str, sql: str) -> int:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return int(await connection.scalar(text(sql)) or 0)
    finally:
        await engine.dispose()


async def _insert_history_row(
    database_url: str,
    *,
    record_id: int,
    accessor_identity_id: int,
    outcome: str,
    actor_type: str,
    scope: str,
    denial_reason: str | None = None,
) -> None:
    """Write a ledger row directly - simulates data stored BEFORE #665."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO health.health_record_access_history "
                    "(record_id, accessor_identity_id, outcome, actor_type, scope, denial_reason) "
                    "VALUES (:record_id, :accessor, :outcome, :actor_type, :scope, :reason)"
                ),
                {
                    "record_id": record_id,
                    "accessor": accessor_identity_id,
                    "outcome": outcome,
                    "actor_type": actor_type,
                    "scope": scope,
                    "reason": denial_reason,
                },
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_owner_reads_write_no_history_row_and_no_outbox_envelope(
    database_url: str, clean_tables: None
) -> None:
    """AC: the plain own-record read and the allowed addressed read write nothing."""
    facade = _health_facade(database_url)
    record_id = await facade.create_record(_IDENTITY)

    await facade.get_own_record(_IDENTITY)
    await facade.get_own_record(_IDENTITY)
    timeline = await facade.get_record_as_owner(_IDENTITY, record_id)
    assert timeline.record_id == record_id

    history_rows = await _count(
        database_url, "SELECT COUNT(*) FROM health.health_record_access_history"
    )
    outbox_rows = await _count(database_url, "SELECT COUNT(*) FROM health.health_outbox")
    assert history_rows == 0
    assert outbox_rows == 0


@pytest.mark.asyncio
async def test_get_access_history_returns_counterparty_and_denied_rows_newest_first(
    database_url: str, clean_tables: None
) -> None:
    """AC: counterparty reads and the addressed read's DENIED path answer the view."""
    facade = _health_facade(database_url)
    record_id = await facade.create_record(_IDENTITY)

    # Counterparty seeds: a doctor console list view and detail view.
    await facade.log_doctor_patient_view(patient_id=_IDENTITY, doctor_id=_DOCTOR)
    await facade.log_doctor_patient_view(
        patient_id=_IDENTITY, doctor_id=_DOCTOR, scope="doctor_patient_detail"
    )
    # An owner read in between writes nothing (#665).
    await facade.get_own_record(_IDENTITY)
    # The addressed read's DENIED path still records its row.
    with pytest.raises(RecordAccessDeniedError):
        await facade.get_record_as_owner(_INTRUDER, record_id)

    view = await facade.get_access_history(_IDENTITY)

    assert len(view.entries) == 3
    denied, detail, listed = view.entries
    # Newest first: the denied intruder attempt is the last recorded read.
    assert denied.actor_id == _INTRUDER
    assert denied.actor_type == "patient"
    assert denied.scope == "full_record"
    assert denied.denied is True
    assert denied.denial_reason == "only the record owner may read this record"

    for entry in (detail, listed):
        assert entry.actor_id == _DOCTOR
        assert entry.actor_type == "doctor"
        assert entry.denied is False
        assert entry.denial_reason is None
    assert detail.scope == "doctor_patient_detail"
    assert listed.scope == "doctor_patients_list"


@pytest.mark.asyncio
async def test_a_pre_existing_self_row_is_invisible_at_read_time(
    database_url: str, clean_tables: None
) -> None:
    """AC: the read filter hides a self row even before the purge migration ran."""
    facade = _health_facade(database_url)
    record_id = await facade.create_record(_IDENTITY)
    await _insert_history_row(
        database_url,
        record_id=record_id,
        accessor_identity_id=_IDENTITY,
        outcome="allowed",
        actor_type="patient",
        scope="full_record",
    )
    await facade.log_doctor_patient_view(patient_id=_IDENTITY, doctor_id=_DOCTOR)

    view = await facade.get_access_history(_IDENTITY)

    assert len(view.entries) == 1
    assert view.entries[0].actor_id == _DOCTOR
    assert view.entries[0].actor_type == "doctor"


@pytest.mark.asyncio
async def test_the_purge_migration_deletes_self_rows_and_retains_cross_patient_denied_rows(
    database_url: str, clean_tables: None
) -> None:
    """AC: the v8.18 purge applies the both-columns predicate; denied rows survive."""
    facade = _health_facade(database_url)
    record_id = await facade.create_record(_IDENTITY)
    await _insert_history_row(
        database_url,
        record_id=record_id,
        accessor_identity_id=_IDENTITY,
        outcome="allowed",
        actor_type="patient",
        scope="full_record",
    )
    await _insert_history_row(
        database_url,
        record_id=record_id,
        accessor_identity_id=_INTRUDER,
        outcome="denied",
        actor_type="patient",
        scope="full_record",
        denial_reason="only the record owner may read this record",
    )
    await facade.log_doctor_patient_view(patient_id=_IDENTITY, doctor_id=_DOCTOR)

    # Round-trip through the pre-purge revision to re-run the v8.18 DELETE.
    # Alembic's async env drives asyncio.run, so it must leave the test's
    # running event loop (asyncio.to_thread runs it on a loop-free thread).
    config = _alembic_config(database_url)
    await asyncio.to_thread(command.downgrade, config, _PRE_PURGE_REVISION)
    await asyncio.to_thread(command.upgrade, config, "head")

    self_rows = await _count(
        database_url,
        "SELECT COUNT(*) FROM health.health_record_access_history "
        f"WHERE actor_type = 'patient' AND accessor_identity_id = {_IDENTITY}",
    )
    denied_rows = await _count(
        database_url,
        "SELECT COUNT(*) FROM health.health_record_access_history "
        f"WHERE outcome = 'denied' AND accessor_identity_id = {_INTRUDER}",
    )
    doctor_rows = await _count(
        database_url,
        "SELECT COUNT(*) FROM health.health_record_access_history "
        f"WHERE actor_type = 'doctor' AND accessor_identity_id = {_DOCTOR}",
    )
    assert self_rows == 0
    assert denied_rows == 1
    assert doctor_rows == 1


@pytest.mark.asyncio
async def test_get_access_history_is_empty_for_an_untouched_record(
    database_url: str, clean_tables: None
) -> None:
    """AC: a fresh record answers an empty list, not an error."""
    facade = _health_facade(database_url)
    await facade.create_record(_IDENTITY)

    view = await facade.get_access_history(_IDENTITY)

    assert view.entries == []


@pytest.mark.asyncio
async def test_audit_facade_delegates_access_history_to_the_health_facade(
    database_url: str, clean_tables: None
) -> None:
    """AC: AuditFacade.get_access_history reaches the same health-schema rows."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    health = HealthFacade(engine)
    await health.create_record(_IDENTITY)
    await health.log_doctor_patient_view(patient_id=_IDENTITY, doctor_id=_DOCTOR)
    audit = AuditFacade(engine=engine, health_facade=health)

    view = await audit.get_access_history(_IDENTITY)

    assert len(view.entries) == 1
    assert view.entries[0].actor_id == _DOCTOR
    assert view.entries[0].actor_type == "doctor"
    await engine.dispose()
