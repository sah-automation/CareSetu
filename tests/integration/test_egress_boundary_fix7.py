"""PHASE-3 FIX-7: dual-ledger write after egress boundary refactor (#227).

Proves that ``read_consented_history`` still writes to BOTH ledgers
(health_record_access_history AND consent_egress_log) after the egress
write was moved to its own consent-transaction.

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

from modules.consent.facade import ConsentFacade
from modules.health.facade import HealthFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PATIENT = 960
_COUNTERPARTY_ID = 780


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_schema(database_url: str) -> Iterator[None]:
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_tables(database_url: str, migrated_schema: None) -> AsyncIterator[None]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE consent.consent_consents, "
                    "consent.consent_events, consent.consent_outbox, "
                    "health.health_patient_records, health.health_record_entries, "
                    "health.health_record_access_history, "
                    "consent.consent_egress_log CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


def _facades(database_url: str) -> tuple[HealthFacade, ConsentFacade]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    consent_facade = ConsentFacade(engine)
    health_facade = HealthFacade(engine, consent_facade=consent_facade)
    return health_facade, consent_facade


@pytest.mark.asyncio
async def test_dual_ledger_write_on_consented_read(database_url: str, clean_tables: None) -> None:
    """AC: consent-gated read writes to BOTH access history and egress log."""
    health_facade, consent_facade = _facades(database_url)

    # Create record shell
    await health_facade.create_record(_PATIENT)

    # Grant consent
    await consent_facade.grant_consent(_PATIENT, "doctor", str(_COUNTERPARTY_ID), "consultations")

    # Consented read should succeed
    timeline = await health_facade.read_consented_history(
        patient_id=_PATIENT,
        scope="consultations",
        counterparty_type="doctor",
        counterparty_id=_COUNTERPARTY_ID,
    )
    assert timeline.patient_id == _PATIENT

    # Verify BOTH ledgers received a row
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            # Check health access history
            access_rows = (
                await conn.execute(
                    text(
                        "SELECT outcome FROM health.health_record_access_history "
                        "WHERE accessor_identity_id = :cp_id"
                    ),
                    {"cp_id": _COUNTERPARTY_ID},
                )
            ).fetchall()
            assert len(access_rows) == 1
            assert access_rows[0].outcome == "allowed"

            # Check consent egress log
            egress_rows = (
                await conn.execute(
                    text(
                        "SELECT consent_id, counterparty_type, record_scope "
                        "FROM consent.consent_egress_log "
                        "WHERE patient_id = :pid"
                    ),
                    {"pid": _PATIENT},
                )
            ).fetchall()
            assert len(egress_rows) == 1
            assert egress_rows[0].counterparty_type == "doctor"
            assert egress_rows[0].record_scope == "consultations"
            assert egress_rows[0].consent_id is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_no_egress_log_on_denied_read(database_url: str, clean_tables: None) -> None:
    """AC: denied read writes to access history ONLY, not egress log."""
    health_facade, _consent_facade = _facades(database_url)

    await health_facade.create_record(_PATIENT)

    # No consent granted - read should be denied
    from modules.health.domain.exceptions import RecordAccessDeniedError

    with pytest.raises(RecordAccessDeniedError):
        await health_facade.read_consented_history(
            patient_id=_PATIENT,
            scope="consultations",
            counterparty_type="doctor",
            counterparty_id=_COUNTERPARTY_ID,
        )

    # Verify access history has a denied row, egress log is empty
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            access_rows = (
                await conn.execute(
                    text(
                        "SELECT outcome FROM health.health_record_access_history "
                        "WHERE accessor_identity_id = :cp_id"
                    ),
                    {"cp_id": _COUNTERPARTY_ID},
                )
            ).fetchall()
            assert len(access_rows) == 1
            assert access_rows[0].outcome == "denied"

            egress_rows = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) AS cnt FROM consent.consent_egress_log "
                        "WHERE patient_id = :pid"
                    ),
                    {"pid": _PATIENT},
                )
            ).fetchone()
            assert egress_rows.cnt == 0
    finally:
        await engine.dispose()
