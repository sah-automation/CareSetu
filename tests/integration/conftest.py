"""Docker-free integration-test database fixture.

Integration tests exercise module facades and schema against a real PostgreSQL.
No Docker is required: the suite connects to the database described by
``TEST_DATABASE_URL`` (falling back to ``DATABASE_URL``) and skips cleanly when
it is unreachable.

Locally that database is the native PostgreSQL service created for CareSetu
(role/database ``caresetu``). In CI the ``integration`` job provides Postgres as
a GitHub-hosted service container and sets ``DATABASE_URL``.
"""

import os

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
