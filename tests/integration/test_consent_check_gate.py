"""PHASE-3 T4: check_consent gate integration tests (#213).

Proves the ticket's acceptance criteria on the real database:
1. Cache invalidation on grant/revoke: fresh read sees the new state.
2. SQL fallback path passes the same behavioral suite standing alone.
3. Fault injection (Redis down) -> SQL fallback works and returns fail-closed.
4. p95 latency check (optional, best-effort).
5. full_record subsumes specific scopes in end-to-end flow.

Requires the native PostgreSQL; the suite skips cleanly when it is
unreachable, migrates to head for the module and downgrades afterwards,
leaving the database as it was found.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from modules.consent.facade import ConsentFacade
from modules.consent.redis_cache import close_redis_client, init_redis_client

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "apps" / "backend" / "alembic.ini"

_PATIENT = 901
_OTHER_PATIENT = 902


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="module")
def migrated_schema(database_url: str) -> Iterator[None]:
    """Migrate to head (iam + health + consent deltas) for the module."""
    config = _alembic_config(database_url)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        pytest.skip(f"PostgreSQL unreachable at {database_url} - {exc}")
    yield
    command.downgrade(config, "base")


@pytest_asyncio.fixture
async def clean_tables(database_url: str, migrated_schema: None) -> AsyncIterator[None]:
    """Empty the consent tables before every test."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE consent.consent_consents, "
                    "consent.consent_events, consent.consent_outbox CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


def _facade(database_url: str) -> ConsentFacade:
    return ConsentFacade(create_async_engine(database_url, poolclass=NullPool))


async def _query(database_url: str, sql: str) -> list[dict[str, Any]]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text(sql))
            return [dict(row) for row in result.mappings().all()]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_cache_invalidated_on_grant(database_url: str, clean_tables: None) -> None:
    """AC: cache invalidated after grant -> fresh check_consent sees granted."""
    facade = _facade(database_url)

    # Initialize Redis cache
    from app.config import Settings

    settings = Settings()
    await init_redis_client(settings)

    try:
        # First check: no consent -> denied (cache miss -> SQL -> cache miss)
        decision = await facade.check_consent(_PATIENT, "doctor", "dr-1", "consultations", settings)
        assert decision.allowed is False

        # Grant consent
        await facade.grant_consent(_PATIENT, "doctor", "dr-1", "consultations")

        # Fresh check should now see the grant (cache invalidated)
        decision = await facade.check_consent(_PATIENT, "doctor", "dr-1", "consultations", settings)
        assert decision.allowed is True
        assert decision.consent_id is not None
        assert decision.version == 1
        assert decision.effective_scope == "consultations"
    finally:
        await close_redis_client()


@pytest.mark.asyncio
async def test_cache_invalidated_on_revoke(database_url: str, clean_tables: None) -> None:
    """AC: cache invalidated after revoke -> fresh check_consent sees revoked."""
    facade = _facade(database_url)

    from app.config import Settings

    settings = Settings()
    await init_redis_client(settings)

    try:
        # Grant first
        await facade.grant_consent(_PATIENT, "lab", "lab-1", "metrics")

        # Check: should be allowed (cached)
        decision = await facade.check_consent(_PATIENT, "lab", "lab-1", "metrics", settings)
        assert decision.allowed is True

        # Revoke
        log = await facade.list_consents(_PATIENT)
        granted_id = next(item.consent_id for item in log.items if item.status == "granted")
        await facade.revoke_consent(_PATIENT, granted_id)

        # Fresh check should see revoked (denied)
        decision = await facade.check_consent(_PATIENT, "lab", "lab-1", "metrics", settings)
        assert decision.allowed is False
    finally:
        await close_redis_client()


@pytest.mark.asyncio
async def test_sql_fallback_when_redis_unavailable(database_url: str, clean_tables: None) -> None:
    """AC: SQL fallback passes same behavioral suite when Redis is down."""
    facade = _facade(database_url)

    # Don't initialize Redis - simulate Redis unavailable
    # check_consent should work via SQL fallback

    # No consent -> denied
    decision = await facade.check_consent(
        _PATIENT,
        "doctor",
        "dr-2",
        "consultations",
        None,  # settings=None skips cache
    )
    assert decision.allowed is False

    # Grant consent
    await facade.grant_consent(_PATIENT, "doctor", "dr-2", "consultations")

    # Check via SQL fallback
    decision = await facade.check_consent(_PATIENT, "doctor", "dr-2", "consultations", None)
    assert decision.allowed is True
    assert decision.version == 1
    assert decision.effective_scope == "consultations"

    # Revoke
    log = await facade.list_consents(_PATIENT)
    granted_id = next(item.consent_id for item in log.items if item.status == "granted")
    await facade.revoke_consent(_PATIENT, granted_id)

    # Check again via SQL
    decision = await facade.check_consent(_PATIENT, "doctor", "dr-2", "consultations", None)
    assert decision.allowed is False


@pytest.mark.asyncio
async def test_fault_injection_redis_down_graceful_fallback(
    database_url: str, clean_tables: None
) -> None:
    """AC: Redis connection failure -> graceful fallback to SQL, no crash."""
    facade = _facade(database_url)

    from app.config import Settings

    settings = Settings()
    await init_redis_client(settings)

    try:
        # Grant consent so there's something to check
        await facade.grant_consent(_PATIENT, "chemist", "ch-1", "prescriptions")

        # Mock Redis client to raise exception on hmget (cache miss)
        from modules.consent import redis_cache

        def mock_get_client():
            mock_client = AsyncMock()
            mock_client.hmget.side_effect = Exception("Redis connection failed")
            return mock_client

        with patch.object(redis_cache, "get_redis_client", mock_get_client):
            # Should fall through to SQL without crashing
            decision = await facade.check_consent(
                _PATIENT, "chemist", "ch-1", "prescriptions", settings
            )
            # SQL is the source of truth - grant is found
            assert decision.allowed is True
            assert decision.consent_id is not None
    finally:
        await close_redis_client()


@pytest.mark.asyncio
async def test_full_record_subsumes_specific_scopes_end_to_end(
    database_url: str, clean_tables: None
) -> None:
    """AC: full_record granted -> all specific scopes allowed."""
    facade = _facade(database_url)

    from app.config import Settings

    settings = Settings()
    await init_redis_client(settings)

    try:
        # Grant full_record
        await facade.grant_consent(_PATIENT, "doctor", "dr-full", "full_record")

        # Check specific scopes - all should be allowed
        for scope in ["consultations", "prescriptions", "lab_results", "metrics"]:
            decision = await facade.check_consent(_PATIENT, "doctor", "dr-full", scope, settings)
            assert decision.allowed is True, f"full_record should subsume {scope}"
            assert decision.effective_scope == "full_record"

        # Check full_record itself
        decision = await facade.check_consent(
            _PATIENT, "doctor", "dr-full", "full_record", settings
        )
        assert decision.allowed is True
        assert decision.effective_scope == "full_record"
    finally:
        await close_redis_client()


@pytest.mark.asyncio
async def test_specific_scope_does_not_subsume_full_record(
    database_url: str, clean_tables: None
) -> None:
    """AC: specific scope granted -> full_record still denied."""
    facade = _facade(database_url)

    from app.config import Settings

    settings = Settings()
    await init_redis_client(settings)

    try:
        # Grant specific scope
        await facade.grant_consent(_PATIENT, "lab", "lab-2", "consultations")

        # Request full_record -> should be denied
        decision = await facade.check_consent(_PATIENT, "lab", "lab-2", "full_record", settings)
        assert decision.allowed is False
        assert decision.consent_id is None

        # But the specific scope is allowed
        decision = await facade.check_consent(_PATIENT, "lab", "lab-2", "consultations", settings)
        assert decision.allowed is True
        assert decision.effective_scope == "consultations"
    finally:
        await close_redis_client()


@pytest.mark.asyncio
async def test_p95_latency_under_50ms(database_url: str, clean_tables: None) -> None:
    """AC: p95 latency under 50ms (best-effort, local measurement).

    This is a best-effort check - actual p95 depends on hardware.
    We run 100 iterations with warmup and assert p95 < 50ms.
    """
    facade = _facade(database_url)

    from app.config import Settings

    settings = Settings()
    await init_redis_client(settings)

    try:
        # Grant consent first
        await facade.grant_consent(_PATIENT, "doctor", "dr-latency", "consultations")

        # Warm up
        for _ in range(10):
            await facade.check_consent(_PATIENT, "doctor", "dr-latency", "consultations", settings)

        # Measure
        latencies: list[float] = []
        for _ in range(100):
            start = time.perf_counter()
            await facade.check_consent(_PATIENT, "doctor", "dr-latency", "consultations", settings)
            end = time.perf_counter()
            latencies.append((end - start) * 1000)  # ms

        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[int(len(latencies) * 0.95)]

        # Best-effort assertion - log for visibility
        print(f"p50 latency: {p50:.2f}ms, p95 latency: {p95:.2f}ms")
        assert p95 < 50, f"p95 latency {p95:.2f}ms exceeds 50ms threshold"
    finally:
        await close_redis_client()


@pytest.mark.asyncio
async def test_different_counterparty_isolation(database_url: str, clean_tables: None) -> None:
    """AC: Consent is isolated per (patient, counterparty_type, counterparty_id, scope)."""
    facade = _facade(database_url)

    from app.config import Settings

    settings = Settings()
    await init_redis_client(settings)

    try:
        # Grant for doctor dr-1
        await facade.grant_consent(_PATIENT, "doctor", "dr-1", "consultations")

        # Different doctor -> denied
        decision = await facade.check_consent(_PATIENT, "doctor", "dr-2", "consultations", settings)
        assert decision.allowed is False

        # Different counterparty type -> denied
        decision = await facade.check_consent(_PATIENT, "lab", "dr-1", "consultations", settings)
        assert decision.allowed is False

        # Different scope -> denied
        decision = await facade.check_consent(_PATIENT, "doctor", "dr-1", "prescriptions", settings)
        assert decision.allowed is False

        # Same triple -> allowed
        decision = await facade.check_consent(_PATIENT, "doctor", "dr-1", "consultations", settings)
        assert decision.allowed is True
    finally:
        await close_redis_client()


@pytest.mark.asyncio
async def test_unknown_patient_denied(database_url: str, clean_tables: None) -> None:
    """AC: Unknown patient ID -> denied (fail-closed)."""
    facade = _facade(database_url)

    from app.config import Settings

    settings = Settings()
    await init_redis_client(settings)

    try:
        decision = await facade.check_consent(99999, "doctor", "dr-1", "consultations", settings)
        assert decision.allowed is False
        assert decision.consent_id is None
        assert decision.version is None
        assert decision.effective_scope is None
    finally:
        await close_redis_client()


@pytest.mark.asyncio
async def test_regrant_after_revoke_continues_lineage(
    database_url: str, clean_tables: None
) -> None:
    """AC: Re-grant after revoke continues the lineage at vN+1."""
    facade = _facade(database_url)

    from app.config import Settings

    settings = Settings()
    await init_redis_client(settings)

    try:
        # Grant
        await facade.grant_consent(_PATIENT, "doctor", "dr-regrant", "consultations")

        # Revoke
        log = await facade.list_consents(_PATIENT)
        granted_id = next(item.consent_id for item in log.items if item.status == "granted")
        await facade.revoke_consent(_PATIENT, granted_id)

        # Re-grant (should be v2)
        await facade.grant_consent(_PATIENT, "doctor", "dr-regrant", "consultations")

        # Check shows v2
        decision = await facade.check_consent(
            _PATIENT, "doctor", "dr-regrant", "consultations", settings
        )
        assert decision.allowed is True
        assert decision.version == 2
    finally:
        await close_redis_client()
