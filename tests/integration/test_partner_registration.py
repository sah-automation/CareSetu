"""PHASE-5 T05: open partner registration against a real PostgreSQL (ticket #249).

Exercises the ``PartnerFacade.register`` seam (with the real ``IamFacade``
created against the same engine) against live Postgres: a doctor/lab/chemist
registers openly with phone + partner type + basic profile, the iam credential
account is created synchronously (ADR-0010), a ``[Registered]`` profile opens
with ``partner.registered`` in the partner outbox in the same transaction, and
a duplicate phone resolves to the existing identity/profile (never a second
row). Requires the native PostgreSQL; the suite skips cleanly when it is
unreachable, and the ``iam`` + ``partner`` schemas are migrated up for the
module and down again afterwards, leaving the database as it was found.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.facade import IamFacade
from modules.partner.facade import PartnerFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PHONE = "+919876543210"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migration(database_url: str) -> Iterator[None]:
    """Migrate all schemas to head for the module, restore base after."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_partner(database_url: str, migration: None) -> AsyncIterator[None]:
    """Empty the iam + partner tables before every test for a clean slate."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE partner.partner_verifications, "
                    "partner.partner_credentials, partner.partner_profiles, "
                    "partner.partner_outbox, partner.partner_service_areas, "
                    "iam.iam_role_grants, iam.iam_sessions, "
                    "iam.iam_otp_challenges, iam.iam_outbox, "
                    "iam.iam_identities CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


async def _query(database_url: str, sql: str) -> list[dict[str, Any]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql))
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


def _facade(database_url: str) -> tuple[IamFacade, PartnerFacade]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    iam = IamFacade(engine=engine, sms_adapter=MockSmsAdapter())
    partner = PartnerFacade(engine=engine, iam_facade=iam)
    return iam, partner


async def test_open_registration_creates_account_and_registered_profile(
    database_url: str, clean_partner: Any
) -> None:
    _, partner = _facade(database_url)

    result = await partner.register(
        phone="9876543210",
        partner_type="doctor",
        practice_address="Station Road, Daltonganj",
        practice_latitude=24.04,
        practice_longitude=84.07,
    )

    assert result.identity_id == 1
    assert result.partner_id == 1
    assert result.partner_type == "doctor"
    assert result.status == "Registered"
    assert result.round == 0
    assert result.created is True

    identities = await _query(database_url, "SELECT id, phone_e164, status FROM iam.iam_identities")
    assert len(identities) == 1
    assert identities[0]["phone_e164"] == _PHONE
    assert identities[0]["status"] == "Unverified"

    profiles = await _query(
        database_url,
        "SELECT id, identity_id, partner_type, status, "
        "practice_address, service_area_id FROM partner.partner_profiles",
    )
    assert len(profiles) == 1
    profile = profiles[0]
    assert profile["identity_id"] == result.identity_id
    assert profile["partner_type"] == "doctor"
    assert profile["status"] == "Registered"
    assert profile["practice_address"] == "Station Road, Daltonganj"
    assert profile["service_area_id"] is None

    partner_outbox = await _query(
        database_url, "SELECT event_type, payload, status FROM partner.partner_outbox"
    )
    assert partner_outbox == [
        {
            "event_type": "partner.registered",
            "payload": {
                "partner_id": result.partner_id,
                "identity_id": result.identity_id,
                "partner_type": "doctor",
            },
            "status": "pending",
        }
    ]

    iam_outbox = await _query(database_url, "SELECT event_type FROM iam.iam_outbox")
    assert [row["event_type"] for row in iam_outbox] == ["partner.registered"]


async def test_duplicate_phone_resolves_to_existing_identity_and_profile(
    database_url: str, clean_partner: Any
) -> None:
    _, partner = _facade(database_url)

    first = await partner.register(
        phone="9876543210",
        partner_type="lab",
        practice_address="Court Road, Daltonganj",
        practice_latitude=24.05,
        practice_longitude=84.06,
    )
    second = await partner.register(
        phone="9876543210",
        partner_type="lab",
        practice_address="Court Road, Daltonganj",
        practice_latitude=24.05,
        practice_longitude=84.06,
    )

    assert first.created is True
    assert second.created is False
    assert second.identity_id == first.identity_id
    assert second.partner_id == first.partner_id
    assert second.status == "Registered"

    identities = await _query(database_url, "SELECT id FROM iam.iam_identities")
    assert len(identities) == 1
    profiles = await _query(database_url, "SELECT id FROM partner.partner_profiles")
    assert len(profiles) == 1

    partner_outbox = await _query(database_url, "SELECT event_type FROM partner.partner_outbox")
    assert [row["event_type"] for row in partner_outbox] == ["partner.registered"]
    # The duplicate resolves to the existing identity without re-publishing
    # partner.registered - neither outbox gains a second event.
    iam_outbox = await _query(database_url, "SELECT event_type FROM iam.iam_outbox")
    assert [row["event_type"] for row in iam_outbox] == ["partner.registered"]


async def test_each_partner_type_registers(database_url: str, clean_partner: Any) -> None:
    _, partner = _facade(database_url)
    expected = {
        "doctor": (1, "doctor"),
        "lab": (2, "lab"),
        "chemist": (3, "chemist"),
    }

    for _phone, (idx, ptype) in expected.items():
        result = await partner.register(
            phone=f"98765432{idx:02d}",
            partner_type=ptype,
            practice_address="Market Road",
            practice_latitude=24.0,
            practice_longitude=84.0,
        )
        assert result.created is True
        assert result.status == "Registered"
        assert result.partner_type == ptype

    profiles = await _query(
        database_url, "SELECT partner_type, status FROM partner.partner_profiles ORDER BY id"
    )
    assert sorted((p["partner_type"], p["status"]) for p in profiles) == [
        ("chemist", "Registered"),
        ("doctor", "Registered"),
        ("lab", "Registered"),
    ]
