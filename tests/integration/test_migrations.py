"""Migration-harness round-trip against the native PostgreSQL (PHASE-1 T1a).

Encodes the async harness acceptance criteria: ``alembic upgrade head``
succeeds on a fresh database (no migration applied), then ``alembic downgrade
base`` leaves the version table empty again. The single-head invariant is
enforced separately by the ``npm run migration-check`` gate. Skips cleanly when
the native PostgreSQL is unreachable, like the rest of the integration suite.
"""

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


async def _version_nums(database_url: str) -> list[str]:
    engine: AsyncEngine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            table_exists = await connection.scalar(
                text(
                    "SELECT EXISTS ("
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = 'alembic_version'"
                    ")"
                )
            )
            if not table_exists:
                return []
            result = await connection.execute(
                text("SELECT version_num FROM public.alembic_version")
            )
            return [row[0] for row in result]
    finally:
        await engine.dispose()


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


def test_upgrade_head_then_downgrade_base_round_trips(database_url: str) -> None:
    _probe_reachability(database_url)
    config = _alembic_config(database_url)
    expected = {r.revision for r in ScriptDirectory.from_config(config).walk_revisions()}

    assert asyncio.run(_version_nums(database_url)) == [], (
        "database must start with no migration applied"
    )

    upgraded = False
    try:
        command.upgrade(config, "head")
        upgraded = True
        assert set(asyncio.run(_version_nums(database_url))) == expected
    finally:
        if upgraded:
            command.downgrade(config, "base")

    assert asyncio.run(_version_nums(database_url)) == []
