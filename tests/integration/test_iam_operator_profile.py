"""PHASE-14B T02: operator profile schema, admin backfill, and invite default (#763).

The operator authority profile (``iam.iam_operator_profiles``) is added by
``v9.8``. These tests pin the ticket's acceptance criteria against a real
PostgreSQL:

- the table exists after ``upgrade head`` (also asserted in ``test_iam_schema``);
- the migration backfills every identity with an ``Active`` ``operator`` role
  grant to an active ``admin`` profile, so the existing operator group keeps its
  authority across the deploy;
- an identity without an active operator grant gets no profile;
- the service layer creates a new invited operator at the non-admin ``operator``
  tier;
- the migration downgrades cleanly.

Requires the native PostgreSQL; the suite skips cleanly when it is unreachable.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from modules.iam.adapters.sms import MockSmsAdapter
from modules.iam.facade import IamFacade

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

#: The revision immediately before the operator-profile migration.
_BEFORE_PROFILE = "a7f3c8e5d21b"

_ACTIVE_OPERATOR_PHONE = "+919333333331"
_SUSPENDED_OPERATOR_PHONE = "+919333333332"
_PATIENT_PHONE = "+919333333333"
_NEW_INVITE_PHONE = "+919333333334"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def profile_schema(database_url: str) -> Iterator[Config]:
    """Migrate to head for the module and restore base afterwards."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except (OperationalError, InterfaceError, OSError) as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield config
    command.downgrade(config, "base")


async def _execute(
    database_url: str, sql: str, params: dict[str, object] | None = None
) -> list[Any]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            result = await connection.execute(text(sql), params or {})
            return list(result.mappings()) if result.returns_rows else []
    finally:
        await engine.dispose()


async def _clear_iam(database_url: str) -> None:
    """Empty the iam tables so the test does not depend on a dirty database.

    ``iam_identities`` cascades to its same-schema children (grants, sessions,
    OTP challenges, MFA enrollments, operator and patient profiles). The
    cross-schema boundary means no other module's rows are touched.
    """
    await _execute(database_url, "TRUNCATE TABLE iam.iam_identities CASCADE")


async def _seed_identity(database_url: str, phone: str) -> int:
    rows = await _execute(
        database_url,
        "INSERT INTO iam.iam_identities (phone_e164, status) "
        "VALUES (:phone, 'Active') RETURNING id",
        {"phone": phone},
    )
    return int(rows[0]["id"])


def test_backfill_promotes_existing_operators_to_active_admin(
    database_url: str, profile_schema: Config
) -> None:
    config = profile_schema
    # Roll the target migration back so identities/grants can exist as they did
    # before the deploy, then run the real upgrade path.
    command.downgrade(config, _BEFORE_PROFILE)
    asyncio.run(_clear_iam(database_url))

    active_operator_id = asyncio.run(_seed_identity(database_url, _ACTIVE_OPERATOR_PHONE))
    suspended_operator_id = asyncio.run(_seed_identity(database_url, _SUSPENDED_OPERATOR_PHONE))
    patient_id = asyncio.run(_seed_identity(database_url, _PATIENT_PHONE))
    asyncio.run(
        _execute(
            database_url,
            "INSERT INTO iam.iam_role_grants (identity_id, role, status) VALUES "
            "(:active, 'operator', 'Active'), (:suspended, 'operator', 'Suspended'), "
            "(:patient, 'patient', 'Active')",
            {
                "active": active_operator_id,
                "suspended": suspended_operator_id,
                "patient": patient_id,
            },
        )
    )

    command.upgrade(config, "head")

    rows = asyncio.run(
        _execute(
            database_url,
            "SELECT identity_id, tier, is_active, mfa_failed_attempts, mfa_locked_until "
            "FROM iam.iam_operator_profiles",
        )
    )
    by_identity = {int(row["identity_id"]): dict(row) for row in rows}

    assert set(by_identity) == {active_operator_id}
    profile = by_identity[active_operator_id]
    assert profile["tier"] == "admin"
    assert profile["is_active"] is True
    assert profile["mfa_failed_attempts"] == 0
    assert profile["mfa_locked_until"] is None


async def test_new_invite_defaults_to_the_operator_tier(
    database_url: str, profile_schema: Config
) -> None:
    await _clear_iam(database_url)
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        facade = IamFacade(engine=engine, sms_adapter=MockSmsAdapter())
        invited = await facade.create_operator_account(_NEW_INVITE_PHONE, invited_by_identity_id=1)
    finally:
        await engine.dispose()

    rows = await _execute(
        database_url,
        "SELECT tier, is_active, mfa_failed_attempts "
        "FROM iam.iam_operator_profiles WHERE identity_id = :identity",
        {"identity": invited.identity_id},
    )

    assert len(rows) == 1
    assert rows[0]["tier"] == "operator"
    assert rows[0]["is_active"] is True
    assert rows[0]["mfa_failed_attempts"] == 0


def test_migration_downgrades_cleanly(database_url: str, profile_schema: Config) -> None:
    config = profile_schema
    command.downgrade(config, _BEFORE_PROFILE)

    rows = asyncio.run(
        _execute(
            database_url,
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'iam' AND table_name = 'iam_operator_profiles'",
        )
    )
    assert rows == []

    # Leave the database at head for the module fixture's own teardown.
    command.upgrade(config, "head")
