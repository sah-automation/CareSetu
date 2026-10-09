"""#668 (FEAT-003): the composition root's counterparty-name resolver, bound into the health facade.

The access-history read carries a name the composition root resolved (#668),
against real PostgreSQL, through the REAL facade ``create_app`` builds. The
partner facade is the collaborator under the test's control: what matters here
is that the trust view answers - with a name, with a null, or at all -
whatever the partner seam does, and that a patient-type actor never resolves
to a name at all (stories 21-22). Same shape as the consent binding prior art
(``test_consent_counterparty_display_name_binding``): one resolver, two
facades, one set of rules.

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
from app.main import create_app
from modules.consent.facade import ConsentFacade
from modules.health.domain.exceptions import RecordAccessDeniedError
from modules.health.facade import HealthFacade
from modules.partner.facade import ProviderProfileNotFoundError

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PATIENT = 960
_INTRUDER = 961
_PARTNER_ID = 777
_PRACTICE_NAME = "Sunrise Clinic"


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
        practice_name: str | None = _PRACTICE_NAME,
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


def _bound_app(
    database_url: str, partner_facade: object
) -> tuple[FastAPI, HealthFacade, ConsentFacade]:
    """A real ``create_app`` with a controlled partner seam on state."""
    app = create_app(settings=Settings(database_url=database_url))
    app.state.partner_facade = partner_facade
    return (
        app,
        cast(HealthFacade, app.state.health_facade),
        cast(ConsentFacade, app.state.consent_facade),
    )


async def _doctor_consent_read(health: HealthFacade, consent: ConsentFacade) -> None:
    """One consented doctor read: the row the view must carry a name for."""
    await health.create_record(_PATIENT)
    await consent.grant_consent(_PATIENT, "doctor", str(_PARTNER_ID), "consultations")
    await health.read_consented_history(
        patient_id=_PATIENT,
        scope="consultations",
        counterparty_type="doctor",
        counterparty_id=_PARTNER_ID,
    )


def _warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and record.name == "app.main"
    ]


@pytest.mark.asyncio
async def test_a_doctor_consent_read_carries_a_resolved_practice_name(
    database_url: str, clean_tables: None
) -> None:
    """AC: a doctor consented read produces a row carrying a resolved name."""
    stub = _StubPartnerFacade()
    _app, health, consent = _bound_app(database_url, stub)

    await _doctor_consent_read(health, consent)

    view = await health.get_access_history(_PATIENT)

    (entry,) = view.entries
    assert entry.actor_id == _PARTNER_ID
    assert entry.actor_type == "doctor"
    assert entry.actor_display_name == _PRACTICE_NAME
    assert entry.denied is False
    # The id stays on the wire beside the name - the name is enrichment.
    # Every parse reached the partner seam for THIS partner id only: once for
    # the grant view ``grant_consent`` answers, once for the history read.
    assert stub.requested == [_PARTNER_ID, _PARTNER_ID]


@pytest.mark.asyncio
async def test_a_partner_profile_miss_keeps_the_access_history_loading(
    database_url: str, clean_tables: None, caplog: pytest.LogCaptureFixture
) -> None:
    """AC: an unresolvable doctor row degrades to null - the view never errors."""
    stub = _StubPartnerFacade(error=ProviderProfileNotFoundError(_PARTNER_ID))
    _app, health, consent = _bound_app(database_url, stub)
    await _doctor_consent_read(health, consent)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.main"):
        view = await health.get_access_history(_PATIENT)

    (entry,) = view.entries
    assert entry.actor_id == _PARTNER_ID
    assert entry.actor_display_name is None
    assert entry.denied is False
    warnings = _warnings(caplog)
    assert warnings
    assert all("doctor" in message for message in warnings)
    # The partner id (and the exception payload) stay out of the log line.
    assert all(str(_PARTNER_ID) not in message for message in warnings)


@pytest.mark.asyncio
async def test_a_partner_profile_read_failure_keeps_the_access_history_loading(
    database_url: str, clean_tables: None, caplog: pytest.LogCaptureFixture
) -> None:
    """AC: a throwing partner seam nulls the name and warns type-only, view intact."""
    stub = _StubPartnerFacade(
        error=RuntimeError(f"partner schema unreachable for partner {_PARTNER_ID}")
    )
    _app, health, consent = _bound_app(database_url, stub)
    await _doctor_consent_read(health, consent)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="app.main"):
        view = await health.get_access_history(_PATIENT)

    (entry,) = view.entries
    assert entry.actor_display_name is None
    warnings = _warnings(caplog)
    assert warnings
    assert all("doctor" in message for message in warnings)
    assert all(str(_PARTNER_ID) not in message for message in warnings)
    assert all("unreachable" not in message for message in warnings)
    assert all("RuntimeError" not in message for message in warnings)


@pytest.mark.asyncio
async def test_lab_and_chemist_rows_resolve_to_null_with_the_resolver_bound(
    database_url: str, clean_tables: None
) -> None:
    """AC (rule order, story 17): lab/chemist keep their role word - null name.

    The type check short-circuits before the partner seam is ever addressed,
    so those rows read honestly with no invented name.
    """
    stub = _StubPartnerFacade()
    _app, health, consent = _bound_app(database_url, stub)
    await health.create_record(_PATIENT)
    await consent.grant_consent(_PATIENT, "doctor", str(_PARTNER_ID), "consultations")
    await consent.grant_consent(_PATIENT, "lab", str(_PARTNER_ID), "consultations")
    await health.read_consented_history(
        patient_id=_PATIENT,
        scope="consultations",
        counterparty_type="doctor",
        counterparty_id=_PARTNER_ID,
    )
    await health.read_consented_history(
        patient_id=_PATIENT,
        scope="consultations",
        counterparty_type="lab",
        counterparty_id=_PARTNER_ID,
    )

    view = await health.get_access_history(_PATIENT)

    by_type = {entry.actor_type: entry.actor_display_name for entry in view.entries}
    assert by_type == {"doctor": _PRACTICE_NAME, "lab": None}
    # The lab type never reached the partner seam.
    assert set(stub.requested) == {_PARTNER_ID}


@pytest.mark.asyncio
async def test_the_cross_patient_denied_row_survives_with_no_name_leak(
    database_url: str, clean_tables: None
) -> None:
    """AC: a cross-patient denied row survives with no name leak (stories 21-22).

    The intruder's refused attempt stays listed - it is not self-access - but
    its identity is never resolved on the record owner's behalf: the patient
    type never reaches the partner seam.
    """
    stub = _StubPartnerFacade()
    _app, health, consent = _bound_app(database_url, stub)
    await _doctor_consent_read(health, consent)
    record_id = await health.create_record(_PATIENT)

    with pytest.raises(RecordAccessDeniedError):
        await health.get_record_as_owner(_INTRUDER, record_id)

    view = await health.get_access_history(_PATIENT)

    denied, doctor = view.entries
    # Newest first: the refused intruder attempt is the last recorded read.
    assert denied.actor_id == _INTRUDER
    assert denied.actor_type == "patient"
    assert denied.denied is True
    assert denied.actor_display_name is None

    assert doctor.actor_id == _PARTNER_ID
    assert doctor.actor_type == "doctor"
    assert doctor.actor_display_name == _PRACTICE_NAME

    # The intruder's patient id never reached the partner seam: every parse
    # was for the doctor's partner id (the grant view + the history read).
    assert set(stub.requested) == {_PARTNER_ID}
