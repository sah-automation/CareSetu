"""#649: the composition root's counterparty-name resolver, end to end.

The consent read models carry a name the composition root resolved (#648),
against real PostgreSQL, through the REAL facade ``create_app`` builds. The
partner facade is the collaborator under the test's control: what matters here
is that the consent read answers - with a name, with a null, or at all -
whatever the partner seam does, so the one surface that proves what was shared
never goes blank.

Requires the native PostgreSQL; the suite skips cleanly when it is
unreachable, migrates to head for the module and downgrades afterwards,
leaving the database as it was found.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings
from app.main import AI_INTAKE_COUNTERPARTY_DISPLAY_NAME, create_app
from modules.consent.facade import ConsentFacade
from modules.health.domain.exceptions import RecordAccessDeniedError
from modules.health.facade import HealthFacade
from modules.intake.adapters import AI_EGRESS_COUNTERPARTY_ID
from modules.partner.facade import ProviderProfileNotFoundError

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PATIENT = 960
_PARTNER_ID = 777


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


class _StubPartnerFacade:
    """The provider-profile seam, replaying a name and recording its calls."""

    def __init__(
        self,
        *,
        practice_name: str | None = "Sunrise Clinic",
        error: Exception | None = None,
    ) -> None:
        self.practice_name = practice_name
        self.error = error
        self.requested: list[int] = []

    async def get_provider_profile(self, partner_id: int) -> SimpleNamespace:
        self.requested.append(partner_id)
        if self.error is not None:
            raise self.error
        return SimpleNamespace(practice_name=self.practice_name)


def _bound_app(database_url: str, partner_facade: object) -> tuple[FastAPI, ConsentFacade]:
    """A real ``create_app`` with a controlled partner seam on state."""
    app = create_app(settings=Settings(database_url=database_url))
    app.state.partner_facade = partner_facade
    return app, cast(ConsentFacade, app.state.consent_facade)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and record.name == "app.main"
    ]


@pytest.mark.asyncio
async def test_the_consent_read_carries_a_resolved_practice_name(
    database_url: str, clean_tables: None
) -> None:
    """A doctor counterparty's consent row carries the practice name end to end."""
    stub = _StubPartnerFacade(practice_name="Sunrise Clinic")
    _app, consent = _bound_app(database_url, stub)

    granted = await consent.grant_consent(_PATIENT, "doctor", str(_PARTNER_ID), "consultations")

    assert granted.counterparty_display_name == "Sunrise Clinic"

    log = await consent.list_consents(patient_id=_PATIENT)

    item = log.items[0]
    assert item.counterparty_display_name == "Sunrise Clinic"
    # The id stays on the wire beside the name - the name is enrichment, not
    # the authorization.
    assert item.counterparty_id == str(_PARTNER_ID)
    # The parse produced the same partner id for the grant view and the log read.
    assert stub.requested == [_PARTNER_ID, _PARTNER_ID]


@pytest.mark.asyncio
async def test_the_ai_pseudo_counterparty_reads_as_the_service_label(
    database_url: str, clean_tables: None
) -> None:
    """``intake-ai`` is a doctor-type row; it must read as a machine, not a clinician.

    Recorded under the doctor type, the id check must win. If the doctor-type
    parse ever ran first, ``int("intake-ai")`` would fail and this row would
    answer null instead of the service label.
    """
    stub = _StubPartnerFacade(error=AssertionError("the partner seam must not be reached"))
    _app, consent = _bound_app(database_url, stub)

    await consent.grant_consent(_PATIENT, "doctor", AI_EGRESS_COUNTERPARTY_ID, "consultations")

    log = await consent.list_consents(patient_id=_PATIENT)

    assert log.items[0].counterparty_display_name == AI_INTAKE_COUNTERPARTY_DISPLAY_NAME
    assert stub.requested == []


@pytest.mark.asyncio
async def test_lab_and_chemist_counterparties_resolve_to_null(
    database_url: str, clean_tables: None
) -> None:
    """Lab and chemist read models hold null until those partner phases land."""
    stub = _StubPartnerFacade()
    _app, consent = _bound_app(database_url, stub)

    await consent.grant_consent(_PATIENT, "lab", str(_PARTNER_ID), "consultations")
    await consent.grant_consent(_PATIENT, "chemist", str(_PARTNER_ID), "consultations")

    log = await consent.list_consents(patient_id=_PATIENT)

    by_type = {item.counterparty_type: item.counterparty_display_name for item in log.items}
    assert by_type == {"lab": None, "chemist": None}
    assert stub.requested == []


@pytest.mark.asyncio
async def test_a_partner_profile_miss_keeps_the_consent_log_loading(
    database_url: str, clean_tables: None, caplog: pytest.LogCaptureFixture
) -> None:
    """A profile miss nulls the name but never the log itself."""
    stub = _StubPartnerFacade(error=ProviderProfileNotFoundError(_PARTNER_ID))
    _app, consent = _bound_app(database_url, stub)
    await consent.grant_consent(_PATIENT, "doctor", str(_PARTNER_ID), "consultations")

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.main"):
        log = await consent.list_consents(patient_id=_PATIENT)

    assert len(log.items) == 1
    assert log.items[0].counterparty_display_name is None
    assert log.items[0].status == "granted"
    warnings = _warnings(caplog)
    assert warnings
    assert all("doctor" in message for message in warnings)
    assert all(str(_PARTNER_ID) not in message for message in warnings)


@pytest.mark.asyncio
async def test_a_partner_profile_read_failure_keeps_the_consent_log_loading(
    database_url: str, clean_tables: None, caplog: pytest.LogCaptureFixture
) -> None:
    """A throwing partner seam nulls the name and warns type-only, log intact."""
    stub = _StubPartnerFacade(
        error=RuntimeError(f"partner schema unreachable for partner {_PARTNER_ID}")
    )
    _app, consent = _bound_app(database_url, stub)
    await consent.grant_consent(_PATIENT, "doctor", str(_PARTNER_ID), "consultations")

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.main"):
        log = await consent.list_consents(patient_id=_PATIENT)

    assert len(log.items) == 1
    assert log.items[0].counterparty_display_name is None
    warnings = _warnings(caplog)
    assert warnings
    assert all("doctor" in message for message in warnings)
    assert all(str(_PARTNER_ID) not in message for message in warnings)
    assert all("unreachable" not in message for message in warnings)
    assert all("RuntimeError" not in message for message in warnings)


@pytest.mark.asyncio
async def test_counterparty_types_stay_isolated_with_the_resolver_bound(
    database_url: str, clean_tables: None
) -> None:
    """A doctor-only grant stays denied for lab and chemist with the binding live."""
    _app, consent = _bound_app(database_url, _StubPartnerFacade())
    engine = create_async_engine(database_url, poolclass=NullPool)
    health = HealthFacade(engine, consent_facade=consent)
    try:
        await health.create_record(_PATIENT)

        await consent.grant_consent(_PATIENT, "doctor", str(_PARTNER_ID), "consultations")

        timeline = await health.read_consented_history(
            patient_id=_PATIENT,
            scope="consultations",
            counterparty_type="doctor",
            counterparty_id=_PARTNER_ID,
        )
        assert timeline.patient_id == _PATIENT

        for other_type in ("lab", "chemist"):
            with pytest.raises(RecordAccessDeniedError):
                await health.read_consented_history(
                    patient_id=_PATIENT,
                    scope="consultations",
                    counterparty_type=other_type,
                    counterparty_id=_PARTNER_ID,
                )
    finally:
        await engine.dispose()
