"""PHASE-2 T1: the five ``iam`` schema tables exist after upgrade (#52).

``alembic upgrade head`` applies ``v1.0__init_iam`` which creates the MOD-001
data foundation - ``iam_identities``, ``iam_otp_challenges``, ``iam_sessions``,
``iam_role_grants`` and ``iam_outbox`` - inside the private ``iam`` schema
(ADR-0003). The test asserts the five tables exist and that the duplicate
arbiter ``phone_e164`` is unique with the FEAT-001 status check on top. Leaves
the database at ``base`` so sibling tests run from a clean slate; skips cleanly
when the native PostgreSQL is unreachable, like the rest of the integration
suite.
"""

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

IAM_TABLES = {
    "iam_identities",
    "iam_otp_challenges",
    "iam_sessions",
    "iam_role_grants",
    "iam_outbox",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


async def _iam_table_names(database_url: str) -> set[str]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'iam'")
            )
            return {row[0] for row in result}
    finally:
        await engine.dispose()


async def _constraints(database_url: str, table: str) -> set[tuple[str, str]]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT tc.constraint_name, COALESCE(kcu.column_name, '') "
                    "FROM information_schema.table_constraints tc "
                    "LEFT JOIN information_schema.key_column_usage kcu "
                    "ON kcu.constraint_name = tc.constraint_name "
                    "AND kcu.table_schema = tc.table_schema "
                    "AND kcu.table_name = tc.table_name "
                    "WHERE tc.table_schema = 'iam' AND tc.table_name = :table"
                ),
                {"table": table},
            )
            return {(row[0], row[1]) for row in result}
    finally:
        await engine.dispose()


def test_upgrade_head_creates_the_five_iam_tables(database_url: str, reachable_db: None) -> None:
    config = _alembic_config(database_url)

    upgraded = False
    try:
        command.upgrade(config, "head")
        upgraded = True

        assert asyncio.run(_iam_table_names(database_url)) == IAM_TABLES

        identity_constraints = asyncio.run(_constraints(database_url, "iam_identities"))
        assert ("uq_iam_identities_phone_e164", "phone_e164") in identity_constraints
        assert ("ck_iam_identities_status", "") in identity_constraints
    finally:
        if upgraded:
            command.downgrade(config, "base")
