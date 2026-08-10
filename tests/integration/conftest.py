"""Docker-free integration-test database fixture.

Integration tests exercise module facades and schema against a real PostgreSQL.
No Docker is required: the suite connects to the database described by
``TEST_DATABASE_URL`` (falling back to ``DATABASE_URL``) and skips cleanly when
it is unreachable.

Locally that database is the native PostgreSQL service created for CareSetu
(role/database ``caresetu``). In CI the ``integration`` job provides Postgres as
a GitHub-hosted service container and sets ``DATABASE_URL``.
"""

import asyncio
import os
import uuid
from collections.abc import Iterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool


def _database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get(
        "DATABASE_URL", "postgresql+asyncpg://caresetu:caresetu@localhost:5432/caresetu"
    )


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _database_url()
    if not url.startswith("postgresql+asyncpg://"):
        pytest.skip("TEST_DATABASE_URL must be an asyncpg URL")
    return url


@pytest_asyncio.fixture(scope="session")
async def db_engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        await engine.dispose()
        pytest.skip(f"PostgreSQL unreachable at {database_url} — install/start the native service")
    yield engine
    await engine.dispose()


@pytest.fixture
def reachable_db(database_url: str) -> None:
    """Skip the test when the native PostgreSQL is unreachable.

    The session-scoped ``db_engine`` already gates the suite; this per-test
    probe keeps each test's skip local and explicit.
    """

    async def probe() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        finally:
            await engine.dispose()

    try:
        asyncio.run(probe())
    except Exception:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - install/start the native service")


@pytest.fixture
def throwaway_schema(database_url: str) -> Iterator[str]:
    """A private schema created for the test and dropped in teardown.

    Each test gets a unique name so sibling tests can run against the same
    native database without colliding.
    """
    schema = f"t_{uuid.uuid4().hex[:12]}"

    async def create() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        finally:
            await engine.dispose()

    async def drop() -> None:
        engine = create_async_engine(database_url, poolclass=NullPool)
        try:
            async with engine.begin() as connection:
                await connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        finally:
            await engine.dispose()

    try:
        asyncio.run(create())
    except Exception:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - install/start the native service")

    yield schema
    asyncio.run(drop())
