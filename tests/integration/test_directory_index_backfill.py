"""PHASE-6 T01 (#307): the directory_index idempotent backfill against Postgres.

The backfill runs as part of the v6.0 migration upgrade - a raw, frozen SQL
INSERT...SELECT. To test it faithfully each test drives the database itself:

1. The module fixture upgrades to the *parent* revision (v5.5, before the
   directory index exists) and restores to base afterward.
2. Each test truncates the partner tables, seeds partners in the states the
   backfill must discriminate between (Active vs not, valid vs expired vs
   unverified vs no credentials, a doctor with one valid and one expired
   credential, doctors vs labs), then upgrades to head.
3. The v6.0 upgrade creates ``partner.partner_directory_index`` and runs the
   backfill; the test asserts the resulting rows (ADR-0012: one row per
   [Active] partner of any type whose credentials are all valid; specialty is
   NULL because no specialty data source exists yet).
4. The test downgrades back to the parent revision so the next test starts
   clean.

Requires the native PostgreSQL; skips cleanly when unreachable.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

#: The revision just before v6.0 - the pre-directory-index state the seeded
#: partners exist in when the backfill runs.
PARENT_REVISION = "2c9f3a7b5d41"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migration_state(database_url: str) -> Iterator[None]:
    """Put the DB at the pre-v6.0 revision for the module; restore base after."""
    config = _alembic_config(database_url)
    command.upgrade(config, PARENT_REVISION)
    yield
    command.downgrade(config, "base")


async def _run(database_url: str, sql: str) -> list[dict[str, object]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(sql))
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


async def _exec(database_url: str, sql: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(sql))
    finally:
        await engine.dispose()


def _seed_partners(database_url: str) -> None:
    async def seed() -> None:
        await _exec(
            database_url,
            "TRUNCATE TABLE partner.partner_verifications, "
            "partner.partner_credentials, partner.partner_profiles, "
            "partner.partner_outbox CASCADE",
        )
        await _exec(
            database_url,
            "INSERT INTO partner.partner_profiles "
            "(id, identity_id, partner_type, status, practice_address, "
            " practice_latitude, practice_longitude) VALUES "
            # 1: Active doctor, credential valid -> indexed
            "(1, 101, 'doctor', 'Active', 'Addr 1', 24.050, 84.070), "
            # 2: Active lab, credential valid -> indexed
            "(2, 102, 'lab', 'Active', 'Addr 2', 24.051, 84.071), "
            # 3: Active doctor with an EXPIRED credential -> not indexed
            "(3, 103, 'doctor', 'Active', 'Addr 3', 24.052, 84.072), "
            # 4: Active doctor with an UNVERIFIED credential -> not indexed
            "(4, 104, 'doctor', 'Active', 'Addr 4', 24.053, 84.073), "
            # 5: Active partner with NO credentials -> not indexed
            "(5, 105, 'chemist', 'Active', 'Addr 5', 24.054, 84.074), "
            # 6: Under Verification partner with valid credentials -> not indexed
            "(6, 106, 'doctor', 'Under Verification', 'Addr 6', 24.055, 84.075), "
            # 7: Active doctor, TWO credentials, one expired -> not indexed
            # (any invalid credential disqualifies the partner, ADR-0012)
            "(7, 107, 'doctor', 'Active', 'Addr 7', 24.056, 84.076)",
        )
        await _exec(
            database_url,
            "INSERT INTO partner.partner_credentials "
            "(profile_id, credential_type, verified, expires_at) VALUES "
            "(1, 'medical_registration', true, now() + interval '30 days'), "
            "(2, 'lab_license', true, now() + interval '30 days'), "
            "(3, 'medical_registration', true, now() - interval '1 day'), "
            "(4, 'medical_registration', false, now() + interval '30 days'), "
            "(6, 'medical_registration', true, now() + interval '30 days'), "
            "(7, 'medical_registration', true, now() + interval '30 days'), "
            "(7, 'qualification_certificate', true, now() - interval '1 day')",
        )

    asyncio.run(seed())


def test_backfill_indexes_only_active_partners_with_valid_credentials(
    database_url: str, reachable_db: None, migration_state: None
) -> None:
    _seed_partners(database_url)

    # Upgrade to head: v6.0 creates the index table and runs the backfill.
    command.upgrade(_alembic_config(database_url), "head")

    rows = asyncio.run(
        _run(
            database_url,
            "SELECT partner_id, practice_latitude, practice_longitude, partner_type, "
            "specialty, is_active FROM partner.partner_directory_index ORDER BY partner_id",
        )
    )

    # Only the two [Active] partners whose credentials are all valid appear.
    assert rows == [
        {
            "partner_id": 1,
            "practice_latitude": Decimal("24.050000"),
            "practice_longitude": Decimal("84.070000"),
            "partner_type": "doctor",
            "specialty": None,
            "is_active": True,
        },
        {
            "partner_id": 2,
            "practice_latitude": Decimal("24.051000"),
            "practice_longitude": Decimal("84.071000"),
            "partner_type": "lab",
            "specialty": None,
            "is_active": True,
        },
    ]

    # Restore the pre-v6.0 state so the next test seeds from a clean schema.
    command.downgrade(_alembic_config(database_url), PARENT_REVISION)


def test_backfill_is_idempotent(
    database_url: str, reachable_db: None, migration_state: None
) -> None:
    _seed_partners(database_url)
    command.upgrade(_alembic_config(database_url), "head")

    count_before = asyncio.run(
        _run(database_url, "SELECT count(*) AS n FROM partner.partner_directory_index")
    )[0]["n"]

    # Re-running the exact backfill statement is a no-op (ON CONFLICT DO
    # NOTHING); the statement mirrors the migration's frozen INSERT...SELECT.
    asyncio.run(
        _exec(
            database_url,
            """
            INSERT INTO partner.partner_directory_index
            (partner_id, practice_latitude, practice_longitude, partner_type,
             specialty, is_active)
        SELECT
            p.id,
            p.practice_latitude,
            p.practice_longitude,
            p.partner_type,
            NULL,
            true
        FROM partner.partner_profiles AS p
        WHERE p.status = 'Active'
          AND EXISTS (
                SELECT 1
                FROM partner.partner_credentials AS c
                WHERE c.profile_id = p.id
          )
          AND NOT EXISTS (
                SELECT 1
                FROM partner.partner_credentials AS c
                WHERE c.profile_id = p.id
                  AND (
                      c.verified = false
                      OR (c.expires_at IS NOT NULL AND c.expires_at <= now())
                      OR c.revoked_at IS NOT NULL
                  )
          )
        ON CONFLICT (partner_id) DO NOTHING
        """,
        )
    )

    count_after = asyncio.run(
        _run(database_url, "SELECT count(*) AS n FROM partner.partner_directory_index")
    )[0]["n"]
    assert count_before == count_after

    command.downgrade(_alembic_config(database_url), PARENT_REVISION)
