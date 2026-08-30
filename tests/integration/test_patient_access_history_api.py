"""PHASE-4 T7: patient access-history view against real PostgreSQL (#241, FEAT-003).

Proves the ticket's acceptance criteria on the native database:

1. ``get_access_history`` returns every ``health_record_access_history`` row
   for the patient's record - owner reads AND denied references - as typed
   ``AccessHistoryEntry`` values: ``actor_id`` / ``actor_type`` / ``scope`` /
   ``accessed_at`` / ``denied`` / ``denial_reason``, newest first (v3.1
   enrichment columns written by ``_log_access``).
2. The empty case answers an empty list, not an error.
3. ``AuditFacade.get_access_history`` delegates to the MOD-003 facade through
   the cross-module seam.

Requires the native PostgreSQL; the suite skips cleanly when it is
unreachable, migrates to head for the module and downgrades afterwards,
leaving the database as it was found.
"""

from __future__ import annotations

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

_IDENTITY = 601
_INTRUDER = 999


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


def _health_facade(database_url: str) -> HealthFacade:
    return HealthFacade(create_async_engine(database_url, poolclass=NullPool))


@pytest.mark.asyncio
async def test_get_access_history_returns_every_entry_with_actor_details(
    database_url: str, clean_tables: None
) -> None:
    """AC: all ledger rows - allowed and denied - with actor_type/scope/reason."""
    facade = _health_facade(database_url)
    record_id = await facade.create_record(_IDENTITY)

    # Two owner reads + one refused intruder read: three ledger rows.
    await facade.get_own_record(_IDENTITY)
    await facade.get_own_record(_IDENTITY)
    with pytest.raises(RecordAccessDeniedError):
        await facade.get_record_as_owner(_INTRUDER, record_id)

    view = await facade.get_access_history(_IDENTITY)

    assert len(view.entries) == 3
    denied, *_ = view.entries
    # Newest first: the denied intruder attempt is the last recorded read.
    assert denied.actor_id == _INTRUDER
    assert denied.actor_type == "patient"
    assert denied.scope == "full_record"
    assert denied.denied is True
    assert denied.denial_reason == "only the record owner may read this record"

    owner_entries = [e for e in view.entries if not e.denied]
    assert len(owner_entries) == 2
    for entry in owner_entries:
        assert entry.actor_id == _IDENTITY
        assert entry.actor_type == "patient"
        assert entry.scope == "full_record"
        assert entry.denied is False
        assert entry.denial_reason is None


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
    await health.get_own_record(_IDENTITY)
    audit = AuditFacade(engine=engine, health_facade=health)

    view = await audit.get_access_history(_IDENTITY)

    assert len(view.entries) == 1
    assert view.entries[0].actor_id == _IDENTITY
    await engine.dispose()
