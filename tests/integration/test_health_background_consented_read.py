"""PHASE-5 #540: the health-background consent-gated read keeps the two-ledger spine.

``read_consented_health_background`` (the doctor detail surface's
health-background section, US-16) must write to BOTH ledgers on a granted
read - ``health_record_access_history`` (outcome=allowed) and
``consent_egress_log`` (citing the ``health_background`` gate scope) - and
fail closed on a denied read, exactly like ``read_consented_history``
(FIX-7, #227). A ``full_record`` grant subsumes the ``health_background``
gate, still egress-citing the gate scope. A granted read with no snapshot on
file serves the typed unset view, not an error.

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
from modules.health.domain.exceptions import RecordAccessDeniedError
from modules.health.facade import HealthFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PATIENT = 961
_COUNTERPARTY_ID = 781

_GATE_SCOPE = "health_background"


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
                    "health.health_background_snapshots, "
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


async def _seed_snapshot(database_url: str, patient_id: int) -> None:
    """Insert one health-background snapshot row directly (the save surface
    belongs to #534; this test exercises the READ gate only)."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO health.health_background_snapshots "
                    "(identity_id, acknowledged_at, blood_group, conditions, "
                    " allergies, medications, immunizations, family_history) "
                    "VALUES (:pid, now(), 'O+', '[\"hypertension\"]'::jsonb, "
                    " '[\"penicillin allergy\"]'::jsonb, '[]'::jsonb, "
                    " '[]'::jsonb, '[]'::jsonb)"
                ),
                {"pid": patient_id},
            )
    finally:
        await engine.dispose()


async def _ledgers(database_url: str, counterparty_id: int) -> tuple[list, list[object]]:
    """Return (access-history rows, egress rows) for the accessor/patient."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            access_rows = (
                await conn.execute(
                    text(
                        "SELECT outcome, scope FROM health.health_record_access_history "
                        "WHERE accessor_identity_id = :cp_id"
                    ),
                    {"cp_id": counterparty_id},
                )
            ).fetchall()
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
    finally:
        await engine.dispose()
    return list(access_rows), list(egress_rows)


@pytest.mark.asyncio
async def test_snapshot_served_and_dual_ledger_write_on_consented_read(
    database_url: str, clean_tables: None
) -> None:
    """AC: granted health-background read serves the snapshot and writes BOTH
    ledgers, egress citing the ``health_background`` gate scope."""
    health_facade, consent_facade = _facades(database_url)
    await consent_facade.grant_consent(_PATIENT, "doctor", str(_COUNTERPARTY_ID), _GATE_SCOPE)
    await _seed_snapshot(database_url, _PATIENT)

    view = await health_facade.read_consented_health_background(
        patient_id=_PATIENT,
        counterparty_type="doctor",
        counterparty_id=_COUNTERPARTY_ID,
    )
    assert view.set is True
    assert view.background is not None
    assert view.background.blood_group == "O+"
    assert view.background.conditions == ["hypertension"]

    access_rows, egress_rows = await _ledgers(database_url, _COUNTERPARTY_ID)
    assert len(access_rows) == 1
    assert access_rows[0].outcome == "allowed"
    assert access_rows[0].scope == _GATE_SCOPE
    assert len(egress_rows) == 1
    assert egress_rows[0].counterparty_type == "doctor"
    assert egress_rows[0].record_scope == _GATE_SCOPE
    assert egress_rows[0].consent_id is not None


@pytest.mark.asyncio
async def test_full_record_grant_subsumes_gate_scope_in_egress(
    database_url: str, clean_tables: None
) -> None:
    """AC: a ``full_record`` grant satisfies the ``health_background`` gate;
    the egress row still cites the narrower scope read."""
    health_facade, consent_facade = _facades(database_url)
    await consent_facade.grant_consent(_PATIENT, "doctor", str(_COUNTERPARTY_ID), "full_record")
    await _seed_snapshot(database_url, _PATIENT)

    view = await health_facade.read_consented_health_background(
        patient_id=_PATIENT,
        counterparty_type="doctor",
        counterparty_id=_COUNTERPARTY_ID,
    )
    assert view.set is True

    _access_rows, egress_rows = await _ledgers(database_url, _COUNTERPARTY_ID)
    assert egress_rows[0].record_scope == _GATE_SCOPE


@pytest.mark.asyncio
async def test_no_egress_log_on_denied_read(database_url: str, clean_tables: None) -> None:
    """AC: no grant - the read fails closed with the access-history ledger row
    only; the egress log stays empty."""
    health_facade, _consent_facade = _facades(database_url)
    await _seed_snapshot(database_url, _PATIENT)

    with pytest.raises(RecordAccessDeniedError):
        await health_facade.read_consented_health_background(
            patient_id=_PATIENT,
            counterparty_type="doctor",
            counterparty_id=_COUNTERPARTY_ID,
        )

    access_rows, egress_rows = await _ledgers(database_url, _COUNTERPARTY_ID)
    assert len(access_rows) == 1
    assert access_rows[0].outcome == "denied"
    assert access_rows[0].scope == _GATE_SCOPE
    assert len(egress_rows) == 0


@pytest.mark.asyncio
async def test_granted_read_without_snapshot_serves_unset_view(
    database_url: str, clean_tables: None
) -> None:
    """AC: granted but nothing on file - the typed unset view is served (no
    error), and the allowed access is still ledged + egressed."""
    health_facade, consent_facade = _facades(database_url)
    await consent_facade.grant_consent(_PATIENT, "doctor", str(_COUNTERPARTY_ID), _GATE_SCOPE)

    view = await health_facade.read_consented_health_background(
        patient_id=_PATIENT,
        counterparty_type="doctor",
        counterparty_id=_COUNTERPARTY_ID,
    )
    assert view.set is False
    assert view.background is None

    access_rows, egress_rows = await _ledgers(database_url, _COUNTERPARTY_ID)
    assert access_rows[0].outcome == "allowed"
    assert egress_rows[0].record_scope == _GATE_SCOPE
