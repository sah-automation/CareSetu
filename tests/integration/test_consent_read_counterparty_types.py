"""PHASE-3 FIX-5: consent-gated read with each counterparty type (#225).

Proves that ``read_consented_history`` works correctly when the caller
specifies ``doctor``, ``lab``, or ``chemist`` as the counterparty type,
rather than the old hardcoded ``"partner"`` value.

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

_PATIENT = 950
_COUNTERPARTY_ID = 777

_COUNTERPARTY_TYPES = ["doctor", "lab", "chemist"]


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
@pytest.mark.parametrize("counterparty_type", _COUNTERPARTY_TYPES)
async def test_consented_read_allowed_for_each_counterparty_type(
    database_url: str, clean_tables: None, counterparty_type: str
) -> None:
    """AC: consent-gated read succeeds with each valid counterparty type."""
    health_facade, consent_facade = _facades(database_url)

    # Create record shell
    await health_facade.create_record(_PATIENT)

    # Grant consent for this counterparty type
    await consent_facade.grant_consent(
        _PATIENT, counterparty_type, str(_COUNTERPARTY_ID), "consultations"
    )

    # Consented read should succeed
    timeline = await health_facade.read_consented_history(
        patient_id=_PATIENT,
        scope="consultations",
        counterparty_type=counterparty_type,
        counterparty_id=_COUNTERPARTY_ID,
    )

    assert timeline.patient_id == _PATIENT


@pytest.mark.asyncio
@pytest.mark.parametrize("counterparty_type", _COUNTERPARTY_TYPES)
async def test_consented_read_denied_when_no_consent(
    database_url: str, clean_tables: None, counterparty_type: str
) -> None:
    """AC: consent-gated read denied when consent absent, for each type."""
    health_facade, _consent_facade = _facades(database_url)

    await health_facade.create_record(_PATIENT)

    with pytest.raises(RecordAccessDeniedError):
        await health_facade.read_consented_history(
            patient_id=_PATIENT,
            scope="consultations",
            counterparty_type=counterparty_type,
            counterparty_id=_COUNTERPARTY_ID,
        )


@pytest.mark.asyncio
async def test_consented_read_denied_records_out_of_vocabulary_scope(
    database_url: str, clean_tables: None
) -> None:
    """A denied read with an unlisted scope is recorded, not rejected.

    The access-history ledger is a happened-events record: the consent gate
    (MOD-004 ``_scope_subsumes``) fails closed against unknown requested
    scopes, and that denial must still be written with the caller's literal
    scope (PHASE-4 T7, #241). Guards the ledger's ``scope`` column against a
    CHECK constraint that would turn this clean domain denial into a 500.
    """
    health_facade, _consent_facade = _facades(database_url)

    await health_facade.create_record(_PATIENT)

    with pytest.raises(RecordAccessDeniedError):
        await health_facade.read_consented_history(
            patient_id=_PATIENT,
            scope="everything",
            counterparty_type="doctor",
            counterparty_id=_COUNTERPARTY_ID,
        )

    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            rows = (
                await connection.execute(
                    text(
                        "SELECT rah.scope, rah.actor_type, rah.outcome, rah.denial_reason "
                        "FROM health.health_record_access_history rah "
                        "JOIN health.health_patient_records r ON r.id = rah.record_id "
                        "WHERE r.identity_id = :patient"
                    ),
                    {"patient": _PATIENT},
                )
            ).all()
    finally:
        await engine.dispose()

    assert len(rows) == 1
    assert rows[0].scope == "everything"
    assert rows[0].actor_type == "doctor"
    assert rows[0].outcome == "denied"


@pytest.mark.asyncio
async def test_counterparty_types_are_isolated(database_url: str, clean_tables: None) -> None:
    """AC: consent for one type does not grant access to another type."""
    health_facade, consent_facade = _facades(database_url)

    await health_facade.create_record(_PATIENT)

    # Grant only for doctor
    await consent_facade.grant_consent(_PATIENT, "doctor", str(_COUNTERPARTY_ID), "consultations")

    # Doctor read should succeed
    timeline = await health_facade.read_consented_history(
        patient_id=_PATIENT,
        scope="consultations",
        counterparty_type="doctor",
        counterparty_id=_COUNTERPARTY_ID,
    )
    assert timeline.patient_id == _PATIENT

    # Lab read should be denied (different type, same id)
    with pytest.raises(RecordAccessDeniedError):
        await health_facade.read_consented_history(
            patient_id=_PATIENT,
            scope="consultations",
            counterparty_type="lab",
            counterparty_id=_COUNTERPARTY_ID,
        )

    # Chemist read should also be denied
    with pytest.raises(RecordAccessDeniedError):
        await health_facade.read_consented_history(
            patient_id=_PATIENT,
            scope="consultations",
            counterparty_type="chemist",
            counterparty_id=_COUNTERPARTY_ID,
        )
