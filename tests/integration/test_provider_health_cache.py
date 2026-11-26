"""ARCH-P2 #841 / MOD-013: provider health read-cache against Postgres + fake Redis.

Proves the observability provider-health cache's observable behavior:

* the first read executes SQL and a fresh second read is a cache hit;
* TTL expiry (simulated by evicting the cached entry) causes the next read to
  execute SQL;
* a Redis miss or error falls back to SQL;
* a malformed or incompatible payload is treated as a miss, never a typed
  failure.

The cache is non-PHI, so no PHI gate case is required. Uses the shared cache
fixtures (#829) and skips cleanly when PostgreSQL is unreachable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, TypeVar

import pytest
import pytest_asyncio
from cache_fixtures import (
    FakeRedis,
    SqlCounter,
    build_observability_facade,
)
from cache_fixtures import fake_redis as fake_redis_client
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from modules.observability.facade import (
    ObservabilityFacade,
    QualityReport,
    window_for,
)

DAYS = 7
OBSERVABILITY_TABLES = (
    "observability.observability_ai_provider_health",
    "observability.observability_ai_usage_daily",
    "observability.consumed_events",
)

_T = TypeVar("_T")


class _ErrorRedis(FakeRedis):
    async def get(self, key: str) -> str | None:
        raise RuntimeError("redis unavailable")

    async def set(self, *args: Any, **kwargs: Any) -> bool | None:
        raise RuntimeError("redis unavailable")


def _cached_key() -> str:
    from_date, to_date = window_for(DAYS)
    return f"provider_health:{from_date.isoformat()}:{to_date.isoformat()}"


@pytest_asyncio.fixture(autouse=True)
async def clean_observability(database_url: str, migrated_schema: None) -> AsyncIterator[None]:
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("TRUNCATE TABLE " + ", ".join(OBSERVABILITY_TABLES) + " CASCADE")
            )
    finally:
        await engine.dispose()
    yield


@pytest.fixture(autouse=True)
def cache_client(fake_redis: FakeRedis) -> FakeRedis:
    return fake_redis


def _build_obs(database_url: str) -> tuple[AsyncEngine, ObservabilityFacade]:
    engine, facade = build_observability_facade(
        database_url=database_url,
        provider_health_cache_ttl_seconds=30,
        return_engine=True,
    )
    return engine, facade  # type: ignore[return-value]


async def _count_selects(engine: AsyncEngine, call: Callable[[], Awaitable[_T]]) -> tuple[_T, int]:
    counter = SqlCounter(engine)
    try:
        result = await call()
        return result, counter.count
    finally:
        counter.detach()


def _read_quality(facade: ObservabilityFacade) -> Callable[[], Awaitable[QualityReport]]:
    return lambda: facade.get_quality(days=DAYS)


@pytest.mark.asyncio
async def test_first_read_executes_sql_and_fresh_second_read_hits(database_url: str) -> None:
    engine, facade = _build_obs(database_url)
    try:
        first, first_selects = await _count_selects(engine, _read_quality(facade))
        assert isinstance(first, QualityReport)
        assert first_selects >= 1

        second, second_selects = await _count_selects(engine, _read_quality(facade))
        assert isinstance(second, QualityReport)
        assert second_selects == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ttl_expiry_causes_next_read_to_execute_sql(
    database_url: str, fake_redis: FakeRedis
) -> None:
    engine, facade = _build_obs(database_url)
    try:
        first, _ = await _count_selects(engine, _read_quality(facade))
        assert isinstance(first, QualityReport)

        _, warm_selects = await _count_selects(engine, _read_quality(facade))
        assert warm_selects == 0

        await fake_redis.delete(_cached_key())

        expired, expired_selects = await _count_selects(engine, _read_quality(facade))
        assert isinstance(expired, QualityReport)
        assert expired_selects >= 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_redis_miss_falls_back_to_sql(database_url: str, fake_redis: FakeRedis) -> None:
    engine, facade = _build_obs(database_url)
    try:
        first, _ = await _count_selects(engine, _read_quality(facade))
        assert isinstance(first, QualityReport)

        await fake_redis.flushdb()

        missed, missed_selects = await _count_selects(engine, _read_quality(facade))
        assert isinstance(missed, QualityReport)
        assert missed_selects >= 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_redis_error_falls_back_to_sql(database_url: str) -> None:
    engine, facade = _build_obs(database_url)
    try:
        with fake_redis_client(_ErrorRedis()):
            result, selects = await _count_selects(engine, _read_quality(facade))
            assert isinstance(result, QualityReport)
            assert selects >= 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", ["[1, 2, 3]", '{"bad": "data"}'])
async def test_malformed_payload_is_a_miss(
    database_url: str, fake_redis: FakeRedis, payload: str
) -> None:
    engine, facade = _build_obs(database_url)
    try:
        fake_redis.store[_cached_key()] = payload

        result, selects = await _count_selects(engine, _read_quality(facade))
        assert isinstance(result, QualityReport)
        assert selects >= 1

        _, warm_selects = await _count_selects(engine, _read_quality(facade))
        assert warm_selects == 0
    finally:
        await engine.dispose()
