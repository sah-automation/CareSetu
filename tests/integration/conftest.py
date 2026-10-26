"""Docker-free integration-test database fixture.

Integration tests exercise module facades and schema against a real PostgreSQL.
No Docker is required: the suite connects to the database described by
``TEST_DATABASE_URL`` (falling back to ``DATABASE_URL``) and skips cleanly when
it is unreachable.

Locally that database is the native PostgreSQL service created for CareSetu
(role/database ``caresetu``). In CI the ``integration`` job provides Postgres as
a GitHub-hosted service container and sets ``DATABASE_URL``.

``migrated_schema`` plus ``clean_tables``/``engine`` are the shared seam for
round-trip modules: one alembic upgrade for the module, then a clean set of
observability tables and outboxes before every test. A round-trip module requests
the fixture and writes its own seed rather than restating the migration path.

Only a connectivity failure skips a test, as ``UNREACHABLE`` marks it: a broken
query or a missing table is a defect in the suite and must fail loudly rather
than read as an unreachable database.
"""

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, text
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from bus.bootstrap import MODULE_SCHEMAS
from bus.dispatcher import discover_outbox_tables
from bus.outbox_ddl import outbox_table

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

#: What "the database is not there" looks like to SQLAlchemy. Only these skip.
UNREACHABLE = (OperationalError, InterfaceError, OSError)

#: Every table the observability aggregates, the rollup ledger and the consumer
#: ledger live in. The union of what the B4a consumer, the B5a rollup and the C1
#: read-route round trips each used to truncate for themselves.
OBSERVABILITY_TABLES: tuple[str, ...] = (
    "observability.observability_ai_provider_health",
    "observability.observability_ai_cost_budget",
    "observability.observability_ai_usage_daily",
    "observability.observability_ai_job_spend",
    "observability.observability_ai_queue_open",
    "observability.observability_care_attribution_edges",
    "observability.observability_attribution_daily",
    "observability.observability_business_daily",
    "observability.observability_alert_events",
    "observability.observability_csp_aggregates",
    "observability.observability_rollup_runs",
    "observability.observability_error_events",
    "observability.observability_http_minute",
    "observability.observability_product_events",
    "observability.observability_product_daily",
    "observability.observability_product_actor_daily",
    "observability.observability_security_signals",
    "observability.observability_evaluation_datasets",
    "observability.observability_evaluation_examples",
    "observability.observability_evaluation_judge_runs",
    "observability.observability_evaluation_scores",
    "observability.consumed_events",
)


async def seed_daltonganj_service_area(connection: AsyncConnection) -> None:
    """Insert the Phase-5 launch default service area into an empty vocabulary.

    The partner registration flow (PHASE-5 #265) defaults a partner with no
    declared ``service_area_id`` to Daltonganj (REQ-008). The seed migration
    v5.4 inserts it on upgrade; integration fixtures that truncate
    ``partner_service_areas`` re-insert it here so the registration under test
    reflects a launched database. Idempotent on the unique ``name``.
    """
    await connection.execute(
        text(
            "INSERT INTO partner.partner_service_areas (id, name) "
            "VALUES (1, 'Daltonganj') ON CONFLICT (name) DO NOTHING"
        )
    )


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
        pytest.skip(f"PostgreSQL unreachable at {database_url} - install/start the native service")
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


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_schema(database_url: str) -> Iterator[None]:
    """Migrate the module under test to head, restore base afterwards.

    Module-scoped so one upgrade/downgrade cycle covers the whole file; the
    per-test clean comes from ``clean_tables``/``engine`` below. A round-trip
    module never needs its own copy of this.
    """
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except UNREACHABLE as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


async def clear_observability_tables(
    connection: AsyncConnection, tables: Sequence[str] = OBSERVABILITY_TABLES
) -> None:
    """Truncate the observability aggregates and both idempotency ledgers.

    ``tables`` takes a narrower list for a module that only reads some of them.
    """
    await connection.execute(text(f"TRUNCATE TABLE {', '.join(tables)} CASCADE"))


async def clear_module_outboxes(connection: AsyncConnection) -> None:
    """Empty every module's outbox, so no sibling module's row reaches a total.

    ``/health`` and the dead-letter alert both count every module's outbox, so a
    row another suite left behind would land in the operator's numbers. Emptied
    through the dispatcher's own table contract rather than with raw SQL naming
    other schemas. This is the one cross-schema step the shared fixture takes, and
    it deletes rows - never schema objects - in another module's own outbox.
    """
    for target in await discover_outbox_tables(connection, MODULE_SCHEMAS):
        await connection.execute(delete(outbox_table(target.table_name, target.schema)))


@pytest_asyncio.fixture
async def clean_tables(database_url: str, migrated_schema: None) -> AsyncIterator[None]:
    """Empty the observability aggregates and every module's outbox before each test."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await clear_observability_tables(connection)
            await clear_module_outboxes(connection)
    except UNREACHABLE as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    finally:
        await engine.dispose()
    yield


@pytest_asyncio.fixture
async def engine(database_url: str, clean_tables: None) -> AsyncIterator[AsyncEngine]:
    """A per-test engine against the migrated schema, aggregates already emptied.

    The session-scoped ``db_engine`` above is the suite-wide handle; this is the
    one a round-trip test passes to the facade and dispatcher under test.
    """
    created = create_async_engine(database_url, poolclass=NullPool)
    try:
        yield created
    finally:
        await created.dispose()
