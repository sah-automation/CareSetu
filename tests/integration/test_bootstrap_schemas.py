"""PHASE-1 T1b: bootstrap schemas + outbox DDL template (ticket #18).

Verifies the acceptance criteria that need a live database:

  1. ``alembic upgrade head`` creates all 11 private module schemas (ADR-0003
     layout) and, per the ticket, no module outbox tables yet.
  2. The outbox/``consumed_events`` DDL template materializes into a throwaway
     schema with the documented row contract (issue #16), so the round-trip
     harness (T2c) can build on it.

Both tests leave the database as they found it (``base`` / no throwaway
schema) so sibling tests run from a clean slate. Skips cleanly when the native
PostgreSQL is unreachable, like the rest of the integration suite.
"""

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from bus.bootstrap import MODULE_SCHEMAS
from bus.outbox_ddl import materialize_consumed_events, materialize_outbox

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

THROWAWAY_SCHEMA = "t1b_throwaway"
THROWAWAY_OUTBOX = "t1b_throwaway_outbox"

OUTBOX_COLUMNS = {
    "id",
    "event_id",
    "event_type",
    "payload",
    "occurred_at",
    "status",
    "attempts",
    "next_attempt_at",
}
LEDGER_COLUMNS = {"event_id", "event_type", "processed_at", "handler_result"}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _probe_reachability(database_url: str) -> None:
    async def probe() -> None:
        engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        finally:
            await engine.dispose()

    try:
        asyncio.run(probe())
    except Exception:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - install/start the native service")


async def _schema_names(database_url: str) -> set[str]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text("SELECT schema_name FROM information_schema.schemata")
            )
            return {row[0] for row in result}
    finally:
        await engine.dispose()


async def _module_schema_table_names(database_url: str) -> list[str]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT table_schema, table_name FROM information_schema.tables "
                    "WHERE table_schema = ANY(:schemas)"
                ),
                {"schemas": list(MODULE_SCHEMAS)},
            )
            return [f"{row[0]}.{row[1]}" for row in result]
    finally:
        await engine.dispose()


async def _column_names(database_url: str, schema: str, table: str) -> set[str]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": schema, "table": table},
            )
            return {row[0] for row in result}
    finally:
        await engine.dispose()


async def _create_throwaway_schema(database_url: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'CREATE SCHEMA "{THROWAWAY_SCHEMA}"'))
    finally:
        await engine.dispose()


async def _drop_throwaway_schema(database_url: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA IF EXISTS "{THROWAWAY_SCHEMA}" CASCADE'))
    finally:
        await engine.dispose()


async def _materialize_template(database_url: str) -> None:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await materialize_outbox(connection, THROWAWAY_SCHEMA, THROWAWAY_OUTBOX)
            await materialize_consumed_events(connection, THROWAWAY_SCHEMA)
    finally:
        await engine.dispose()


def test_upgrade_head_creates_all_eleven_module_schemas(database_url: str) -> None:
    _probe_reachability(database_url)
    config = _alembic_config(database_url)

    upgraded = False
    try:
        command.upgrade(config, "head")
        upgraded = True

        schemas = asyncio.run(_schema_names(database_url))
        assert set(MODULE_SCHEMAS) <= schemas, (
            f"expected all 11 module schemas after upgrade, missing: "
            f"{set(MODULE_SCHEMAS) - schemas}"
        )

        tables = asyncio.run(_module_schema_table_names(database_url))
        assert tables == [], (
            "no module outbox/domain tables may exist after the bootstrap migration, "
            f"found: {tables}"
        )
    finally:
        if upgraded:
            command.downgrade(config, "base")


def test_outbox_template_materializes_throwaway_tables(database_url: str) -> None:
    _probe_reachability(database_url)

    created = False
    try:
        asyncio.run(_create_throwaway_schema(database_url))
        created = True
        asyncio.run(_materialize_template(database_url))

        outbox_columns = asyncio.run(
            _column_names(database_url, THROWAWAY_SCHEMA, THROWAWAY_OUTBOX)
        )
        assert outbox_columns == OUTBOX_COLUMNS

        ledger_columns = asyncio.run(
            _column_names(database_url, THROWAWAY_SCHEMA, "consumed_events")
        )
        assert ledger_columns == LEDGER_COLUMNS
    finally:
        if created:
            asyncio.run(_drop_throwaway_schema(database_url))
