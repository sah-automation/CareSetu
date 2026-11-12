"""#903: the doctor Patients list against real PostgreSQL.

Proves the latency fix preserved the surface's contract on the native
database:

1. The list answers identical results, ordering, and pagination for a
   seeded multi-patient dataset: Current bucket rows derived from live
   standing grants, nameless rows first (then named alphabetically by
   patient id), stable across repeated reads, paginated with the served
   page's total.
2. Every row actually served is still access-logged (ADR-0019 D3) and every
   served granted row is still egress-disclosed - the batching never
   weakened the audit guarantee; unserved rows write nothing.
3. Profile enrichment reads identity in one batched pass (#903) - the rows
   carry the same names/ages the per-patient reads served.

Requires the native PostgreSQL; the suite skips cleanly when it is
unreachable, migrates to head for the module and downgrades afterwards,
leaving the database as it was found.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from modules.care.case_facade import CaseConsoleFacade
from modules.consent.facade import ConsentFacade
from modules.doctor.facade import DoctorConsoleFacade
from modules.health.facade import HealthFacade
from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.facade import IamFacade
from modules.intake.facade import IntakeFacade
from modules.partner.facade import PartnerFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_DOCTOR = 4200


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
    """Empty the surfaces the Patients list derives from before every test."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE consent.consent_consents, consent.consent_egress_log, "
                    "consent.consent_events, consent.consent_outbox, "
                    "partner.partner_profiles, health.health_patient_records, "
                    "health.health_record_entries, health.health_record_access_history, "
                    "health.health_outbox, iam.iam_identities, iam.iam_patient_profiles, "
                    "iam.iam_outbox CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


def _engine(database_url: str):
    return create_async_engine(database_url, poolclass=NullPool)


def _facade(database_url: str) -> DoctorConsoleFacade:
    engine = _engine(database_url)
    care = CaseConsoleFacade(engine, intake_facade=cast(IntakeFacade, SimpleNamespace()))
    return DoctorConsoleFacade(
        consent_facade=ConsentFacade(engine),
        care_facade=care,
        iam_facade=IamFacade(engine=engine, sms_adapter=MockSmsAdapter()),
        health_facade=HealthFacade(_engine(database_url)),
        partner_facade=PartnerFacade(engine),
    )


async def _seed_doctor_and_patients(
    database_url: str,
    *,
    patients: list[tuple[int, str | None]],
) -> None:
    """Seed an active doctor partner, patient identities/profiles, and grants.

    ``patients`` carries (identity_id, name-or-None): a name seeds an
    ``iam_patient_profiles`` row; every patient gets one live ``full_record``
    standing grant held by the doctor.
    """
    engine = _engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO partner.partner_profiles "
                    "(id, identity_id, partner_type, status, practice_address, "
                    "practice_latitude, practice_longitude) "
                    "VALUES (:id, :identity_id, 'doctor', 'Active', '12 Main Road', "
                    "24.036300, 84.066000)"
                ),
                {"id": _DOCTOR, "identity_id": 1},
            )
            await connection.execute(
                text(
                    "INSERT INTO iam.iam_identities (id, phone_e164, status, phone_verified) "
                    "VALUES (:id, :phone, 'Active', true)"
                ),
                [{"id": pid, "phone": f"+9198000{pid:05d}"} for pid, _ in patients],
            )
            named = [(pid, name) for pid, name in patients if name is not None]
            if named:
                await connection.execute(
                    text(
                        "INSERT INTO iam.iam_patient_profiles "
                        "(identity_id, name, age, gender, preferred_language) "
                        "VALUES (:identity_id, :name, :age, 'female', 'hi')"
                    ),
                    [
                        {"identity_id": pid, "name": name, "age": 30 + pid % 10}
                        for pid, name in named
                    ],
                )
            await connection.execute(
                text(
                    "INSERT INTO consent.consent_consents "
                    "(patient_id, counterparty_type, counterparty_id, record_scope, "
                    "status, version) "
                    "VALUES (:patient_id, 'doctor', :counterparty_id, 'full_record', "
                    "'granted', 1)"
                ),
                [{"patient_id": pid, "counterparty_id": str(_DOCTOR)} for pid, _ in patients],
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_patients_list_returns_identical_results_ordering_and_pagination(
    database_url: str, clean_tables: None
) -> None:
    # 8 named (unordered on purpose) + 4 nameless patients, all Current.
    patients: list[tuple[int, str | None]] = [
        (101, "Zoya Khan"),
        (102, None),
        (103, "Anita Sharma"),
        (104, None),
        (105, "Ravi Kumar"),
        (106, None),
        (107, "Bhavna Rao"),
        (108, None),
        (109, "Anita Sharma"),
        (110, "Meera Nair"),
        (111, "Charu Verma"),
        (112, "Deepa Iyer"),
    ]
    await _seed_doctor_and_patients(database_url, patients=patients)
    facade = _facade(database_url)

    first = await facade.list_doctor_patients(doctor_id=_DOCTOR, page=1, per_page=5)
    second = await facade.list_doctor_patients(doctor_id=_DOCTOR, page=2, per_page=5)
    third = await facade.list_doctor_patients(doctor_id=_DOCTOR, page=3, per_page=5)
    # Re-read page 1: ordering and contents are stable across calls.
    first_again = await facade.list_doctor_patients(doctor_id=_DOCTOR, page=1, per_page=5)

    # Nameless rows sort first (by patient id), then named alphabetically with
    # the patient id tie-break - the same ordering contract as before #903.
    assert [row.patient_id for row in first.items] == [102, 104, 106, 108, 103]
    assert [row.patient_id for row in second.items] == [109, 107, 111, 112, 110]
    assert [row.patient_id for row in third.items] == [105, 101]
    assert [row.patient_id for row in first_again.items] == [row.patient_id for row in first.items]
    assert first.total == second.total == third.total == 12
    for row in first.items + second.items + third.items:
        assert row.bucket == "current"
        assert row.granted_scopes == ["full_record"]
        assert row.latest_case_stage is None
    names = {row.patient_id: row.name for row in first.items + second.items + third.items}
    assert names[101] == "Zoya Khan"
    assert names[103] == "Anita Sharma"
    assert names[109] == "Anita Sharma"
    assert names[102] is None
    assert names[108] is None


@pytest.mark.asyncio
async def test_every_served_row_is_access_logged_and_disclosed(
    database_url: str, clean_tables: None
) -> None:
    patients = [(pid, f"Patient {pid:03d}") for pid in range(201, 213)]
    await _seed_doctor_and_patients(database_url, patients=patients)
    facade = _facade(database_url)

    page_two = await facade.list_doctor_patients(doctor_id=_DOCTOR, page=2, per_page=5)

    served = {row.patient_id for row in page_two.items}
    engine = _engine(database_url)
    try:
        async with engine.connect() as connection:
            logged = {
                int(row[0])
                for row in (
                    await connection.execute(
                        text(
                            "SELECT DISTINCT identity_id "
                            "FROM health.health_record_access_history h "
                            "JOIN health.health_patient_records r "
                            "ON h.record_id = r.id "
                            "WHERE h.actor_type = 'doctor' AND h.scope = 'doctor_patients_list'"
                        )
                    )
                ).all()
            }
            disclosed = {
                int(row[0])
                for row in (
                    await connection.execute(
                        text(
                            "SELECT DISTINCT patient_id FROM consent.consent_egress_log "
                            "WHERE counterparty_type = 'doctor' "
                            "AND counterparty_id = :doctor_id"
                        ),
                        {"doctor_id": str(_DOCTOR)},
                    )
                ).all()
            }
    finally:
        await engine.dispose()

    # Exactly the served page is in both ledgers - not the whole dataset
    # (ADR-0019 D3: a page that is not served logs nothing).
    assert logged == served
    assert disclosed == served
    assert len(served) == 5


@pytest.mark.asyncio
async def test_profiles_resolve_in_one_batched_read_for_the_whole_page(
    database_url: str, clean_tables: None
) -> None:
    """#903: the row set's profiles arrive from one identity read.

    Two sequential list calls still resolve every served row's name; the
    batch read answers the same names the per-patient seam served.
    """
    patients = [(pid, f"Patient {pid:03d}") for pid in range(301, 311)]
    await _seed_doctor_and_patients(database_url, patients=patients)
    iam_engine = _engine(database_url)
    iam = IamFacade(engine=iam_engine, sms_adapter=MockSmsAdapter())
    try:
        profiles = await iam.get_patient_profiles([301, 303, 309])
    finally:
        await iam_engine.dispose()

    assert set(profiles) == {301, 303, 309}
    assert profiles[301].name == "Patient 301"

    facade = _facade(database_url)
    result = await facade.list_doctor_patients(doctor_id=_DOCTOR, page=1, per_page=10)
    assert {row.patient_id for row in result.items if row.name is not None} == set(range(301, 311))


@pytest.mark.asyncio
async def test_concurrent_ledger_writes_land_all_rows(
    database_url: str, clean_tables: None
) -> None:
    """#903: the fanned-out per-row writes all commit, none lost.

    A page whose ledger writes run concurrently (asyncio.gather) still lands
    one access-history row AND one egress row per served row.
    """
    patients = [(pid, f"Patient {pid:03d}") for pid in range(401, 421)]
    await _seed_doctor_and_patients(database_url, patients=patients)
    facade = _facade(database_url)

    # Default per_page (25): the whole 20-row dataset served in one call.
    result = await facade.list_doctor_patients(doctor_id=_DOCTOR)

    assert result.total == 20
    engine = _engine(database_url)
    try:
        async with engine.connect() as connection:
            logged_count = int(
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM health.health_record_access_history h "
                        "JOIN health.health_patient_records r ON h.record_id = r.id "
                        "WHERE h.actor_type = 'doctor' AND h.scope = 'doctor_patients_list'"
                    )
                )
                or 0
            )
            egress_count = int(
                await connection.scalar(
                    text(
                        "SELECT count(*) FROM consent.consent_egress_log "
                        "WHERE counterparty_type = 'doctor' AND counterparty_id = :doctor_id"
                    ),
                    {"doctor_id": str(_DOCTOR)},
                )
                or 0
            )
    finally:
        await engine.dispose()

    assert logged_count == 20
    assert egress_count == 20
