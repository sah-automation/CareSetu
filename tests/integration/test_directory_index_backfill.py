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

#: The revision just before the v8.6 active-backfill (#458) - the schema state
#: the missed-population partners exist in when the backfill upgrade runs.
ACTIVE_BACKFILL_PARENT_REVISION = "b38d0e62f4a7"


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


# ---------------------------------------------------------------------------
# v8.6 active backfill (#458) - the runtime activation seam's semantics applied
# to the population the v6_0 one-shot backfill missed.
# ---------------------------------------------------------------------------


def _seed_active_backfill_population(database_url: str) -> None:
    """Seed the pre-backfill states the v8.6 migration must discriminate (at v8.5)."""

    async def seed() -> None:
        await _exec(
            database_url,
            "TRUNCATE TABLE partner.partner_verifications, "
            "partner.partner_credentials, partner.partner_profiles, "
            "partner.partner_directory_index, partner.partner_outbox CASCADE",
        )
        await _exec(
            database_url,
            "INSERT INTO partner.partner_profiles "
            "(id, identity_id, partner_type, status, practice_address, "
            " practice_latitude, practice_longitude) VALUES "
            # 11: Active doctor, approved round-1 credential UNVERIFIED ->
            #     the missed population (approval predates the seam).
            "(11, 111, 'doctor', 'Active', 'Addr 11', 24.060, 84.080), "
            # 12: Active lab, round-1 already verified but NO index row.
            "(12, 112, 'lab', 'Active', 'Addr 12', 24.061, 84.081), "
            # 13: Active doctor mid-grace: round-1 approved, round-2 QUEUED ->
            #     round-2 credential must NOT be sealed.
            "(13, 113, 'doctor', 'Active', 'Addr 13', 24.062, 84.082), "
            # 14: Active doctor, approved round-1 credential EXPIRED -> hidden.
            "(14, 114, 'doctor', 'Active', 'Addr 14', 24.063, 84.083), "
            # 15: Active doctor, approved round-1 credential REVOKED -> hidden.
            "(15, 115, 'doctor', 'Active', 'Addr 15', 24.064, 84.084), "
            # 16: Under Verification partner, queued round, unverified -> untouched.
            "(16, 116, 'doctor', 'Under Verification', 'Addr 16', 24.065, 84.085), "
            # 18: Active doctor, verified + valid, with a STALE index row
            #     (old location, is_active = false) -> refreshed, not duplicated.
            "(18, 118, 'doctor', 'Active', 'Addr 18', 24.068, 84.088)",
        )
        await _exec(
            database_url,
            "INSERT INTO partner.partner_verifications "
            "(profile_id, round, status, decision) VALUES "
            "(11, 1, 'approved', 'approved'), "
            "(12, 1, 'approved', 'approved'), "
            "(13, 1, 'approved', 'approved'), "
            "(13, 2, 'queued', NULL), "
            "(14, 1, 'approved', 'approved'), "
            "(15, 1, 'approved', 'approved'), "
            "(16, 1, 'queued', NULL), "
            "(18, 1, 'approved', 'approved')",
        )
        await _exec(
            database_url,
            "INSERT INTO partner.partner_credentials "
            "(profile_id, round, credential_type, verified, expires_at, revoked_at) VALUES "
            "(11, 1, 'medical_registration', false, now() + interval '30 days', NULL), "
            "(12, 1, 'lab_license', true, now() + interval '30 days', NULL), "
            "(13, 1, 'medical_registration', true, now() + interval '30 days', NULL), "
            "(13, 2, 'medical_registration', false, now() + interval '30 days', NULL), "
            "(14, 1, 'medical_registration', true, now() - interval '1 day', NULL), "
            "(15, 1, 'medical_registration', true, now() + interval '30 days', now()), "
            "(16, 1, 'medical_registration', false, now() + interval '30 days', NULL), "
            "(18, 1, 'medical_registration', true, now() + interval '30 days', NULL)",
        )
        await _exec(
            database_url,
            "INSERT INTO partner.partner_directory_index "
            "(partner_id, practice_latitude, practice_longitude, partner_type, is_active) "
            "VALUES (18, 9.000000, 9.000000, 'doctor', false)",
        )

    asyncio.run(seed())


def test_active_backfill_seals_approved_rounds_and_indexes_eligible_partners(
    database_url: str, reachable_db: None, migration_state: None
) -> None:
    """FEAT-004 (#458): the v8.6 backfill stamps only approved rounds and upserts
    the index with the runtime seam's exact conditions.

    Approval is the only path to ``Active`` (no auto-approve), so every
    ``[Active]`` partner carries an approved verification round and gets the
    seam's index upsert - even one whose approved credential has since expired
    or been revoked: the read-side ``provider_visible`` predicate (#457)
    hides such a partner on every read, exactly as it would hide a partner the
    live seam indexed at approval (ADR-0011 lazy read-hide).
    """
    # Start from the pre-backfill revision (v8.5) so the backfill upgrade runs.
    command.upgrade(_alembic_config(database_url), ACTIVE_BACKFILL_PARENT_REVISION)
    _seed_active_backfill_population(database_url)

    # Upgrade to head: v8.6 stamps approved-round credentials and upserts the
    # directory index with the runtime seam's semantics (#458).
    command.upgrade(_alembic_config(database_url), "head")

    rows = asyncio.run(
        _run(
            database_url,
            "SELECT profile_id, round, verified FROM partner.partner_credentials "
            "ORDER BY profile_id, round",
        )
    )

    # Only credentials in an APPROVED round of an [Active] partner are sealed;
    # the grace round (13/2), the queued Under-Verification round (16/1) and
    # revoked rows are never stamped verified.
    assert rows == [
        {"profile_id": 11, "round": 1, "verified": True},
        {"profile_id": 12, "round": 1, "verified": True},
        {"profile_id": 13, "round": 1, "verified": True},
        {"profile_id": 13, "round": 2, "verified": False},
        {"profile_id": 14, "round": 1, "verified": True},
        {"profile_id": 15, "round": 1, "verified": True},
        {"profile_id": 16, "round": 1, "verified": False},
        {"profile_id": 18, "round": 1, "verified": True},
    ]

    indexed = asyncio.run(
        _run(
            database_url,
            "SELECT partner_id FROM partner.partner_directory_index ORDER BY partner_id",
        )
    )

    # Every [Active] partner with an approved verification round gets the seam's
    # upsert (11, 12, 13, 14, 15, 18); the only partner left out is the
    # Under-Verification partner (16) who holds no approved round. The expired
    # (14) and revoked (15) rows stay provider-invisible on the read side.
    assert [row["partner_id"] for row in indexed] == [11, 12, 13, 14, 15, 18]

    refreshed = asyncio.run(
        _run(
            database_url,
            "SELECT partner_id, is_active, practice_latitude, practice_longitude "
            "FROM partner.partner_directory_index WHERE partner_id = 18",
        )
    )

    # The existing row was refreshed, never duplicated (ON CONFLICT DO UPDATE).
    assert refreshed == [
        {
            "partner_id": 18,
            "is_active": True,
            "practice_latitude": Decimal("24.068000"),
            "practice_longitude": Decimal("84.088000"),
        },
    ]

    command.downgrade(_alembic_config(database_url), ACTIVE_BACKFILL_PARENT_REVISION)


def test_active_backfill_is_idempotent(
    database_url: str, reachable_db: None, migration_state: None
) -> None:
    """FEAT-004 (#458): re-running the backfill against a consistent DB is a no-op.

    No verified-state drifts back and no index row is added or removed - the
    stamp is guarded by ``verified = false`` and the upsert converges on the
    same rows.
    """
    command.upgrade(_alembic_config(database_url), ACTIVE_BACKFILL_PARENT_REVISION)
    _seed_active_backfill_population(database_url)
    command.upgrade(_alembic_config(database_url), "head")

    count_before = asyncio.run(
        _run(database_url, "SELECT count(*) AS n FROM partner.partner_directory_index")
    )[0]["n"]
    checked_before = asyncio.run(
        _run(
            database_url,
            "SELECT count(*) AS n FROM partner.partner_credentials "
            "WHERE verified = false AND revoked_at IS NULL",
        )
    )[0]["n"]

    # Re-running the migration's exact statements against a consistent DB is a
    # no-op: no verified-state drifts back and no index row is added.
    asyncio.run(
        _exec(
            database_url,
            """
            UPDATE partner.partner_credentials AS c
            SET verified = true,
                updated_at = now()
            WHERE c.verified = false
              AND c.revoked_at IS NULL
              AND EXISTS (
                    SELECT 1
                    FROM partner.partner_profiles AS p
                    WHERE p.id = c.profile_id
                      AND p.status = 'Active'
              )
              AND EXISTS (
                    SELECT 1
                    FROM partner.partner_verifications AS v
                    WHERE v.profile_id = c.profile_id
                      AND v.round = c.round
                      AND v.status = 'approved'
              )
            """,
        )
    )
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
                    FROM partner.partner_verifications AS v
                    WHERE v.profile_id = p.id
                      AND v.status = 'approved'
              )
            ON CONFLICT (partner_id) DO UPDATE SET
                practice_latitude = EXCLUDED.practice_latitude,
                practice_longitude = EXCLUDED.practice_longitude,
                partner_type = EXCLUDED.partner_type,
                is_active = true,
                updated_at = now()
            """,
        )
    )

    count_after = asyncio.run(
        _run(database_url, "SELECT count(*) AS n FROM partner.partner_directory_index")
    )[0]["n"]
    checked_after = asyncio.run(
        _run(
            database_url,
            "SELECT count(*) AS n FROM partner.partner_credentials "
            "WHERE verified = false AND revoked_at IS NULL",
        )
    )[0]["n"]
    assert count_before == count_after
    assert checked_before == checked_after

    command.downgrade(_alembic_config(database_url), ACTIVE_BACKFILL_PARENT_REVISION)
