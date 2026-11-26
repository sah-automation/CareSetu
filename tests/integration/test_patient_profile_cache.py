"""ARCH-P2 #838 / FEAT-008: patient profile read-cache against Postgres + fake Redis.

Proves the ``MOD-001`` profile cache's observable behavior: SQL on the first
read, a cache hit on a fresh second read, invalidation on save, safe SQL
fallback on a miss/error, malformed payloads treated as misses, and the PHI gate.

Uses the shared cache fixtures (#829) and skips cleanly when PostgreSQL is
unreachable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from cache_fixtures import FakeRedis, SqlCounter, build_iam_facade
from cache_fixtures import fake_redis as fake_redis_client
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from modules.iam.facade import IamFacade
from modules.iam.identity_facade import PatientProfile

_PROFILE = PatientProfile(
    name="Asha Devi",
    age=34,
    gender="female",
    preferred_language="hi",
    area="Daltonganj",
    emergency_contact="+9199876543211",
)

_UPDATED_PROFILE = _PROFILE.model_copy(update={"name": "Asha Devi Kumari", "area": "Latehar"})

_PHONE = "9876543210"
_PHI_ENV_VARS = ("PHI_CACHE_ENABLED", "REDIS_URL")
_REDIS_URL = "redis://localhost:6379/0"


class _ErrorRedis(FakeRedis):
    """A fake Redis whose reads and writes always fail."""

    async def get(self, key: str) -> str | None:
        raise RuntimeError("redis unavailable")

    async def set(self, *args: Any, **kwargs: Any) -> bool | None:
        raise RuntimeError("redis unavailable")


@pytest_asyncio.fixture(autouse=True)
async def clean_iam(database_url: str, migrated_schema: None) -> AsyncIterator[None]:
    """Empty the iam tables before every test for a clean slate."""
    engine = create_async_engine(database_url, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "TRUNCATE TABLE iam.iam_patient_profiles, iam.iam_role_grants, "
                    "iam.iam_sessions, iam.iam_otp_challenges, iam.iam_outbox, "
                    "iam.consumed_events, iam.iam_identities CASCADE"
                )
            )
    finally:
        await engine.dispose()
    yield


@pytest.fixture(autouse=True)
def clear_phi_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the PHI gate off unless a test opts in."""
    for name in _PHI_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def phi_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the cache with the PHI gate open and a configured Redis URL."""
    monkeypatch.setenv("PHI_CACHE_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", _REDIS_URL)


@pytest.fixture(autouse=True)
def cache_client(fake_redis: FakeRedis) -> FakeRedis:
    """Install the fake Redis as the shared cache client for every test."""
    return fake_redis


def _build_iam(database_url: str) -> tuple[AsyncEngine, IamFacade]:
    return build_iam_facade(database_url=database_url, return_engine=True)


async def _seed_profile(iam: IamFacade) -> int:
    registered = await iam.register_patient(_PHONE)
    await iam.save_patient_profile(registered.identity_id, _PROFILE)
    return registered.identity_id


async def _read_with_counter(
    iam: IamFacade, engine: AsyncEngine, identity_id: int
) -> tuple[PatientProfile | None, int]:
    counter = SqlCounter(engine)
    try:
        result = await iam.get_patient_profile(identity_id)
        return result, counter.count
    finally:
        counter.detach()


async def _assert_sql_read(
    iam: IamFacade,
    engine: AsyncEngine,
    identity_id: int,
    expected: PatientProfile = _PROFILE,
) -> None:
    result, selects = await _read_with_counter(iam, engine, identity_id)
    assert result == expected
    assert selects >= 1


def _seed_cached_payload(cache: FakeRedis, identity_id: int, payload: str) -> None:
    # The brief asks the malformed-payload case to be seeded through the fake
    # Redis, so this is the only place that names the cache key.
    cache.store[f"profile:{identity_id}"] = payload


@pytest.mark.asyncio
async def test_first_read_executes_sql_and_fresh_second_read_hits(
    database_url: str, phi_enabled: None
) -> None:
    engine, iam = _build_iam(database_url)
    try:
        identity_id = await _seed_profile(iam)

        await _assert_sql_read(iam, engine, identity_id)

        result, selects = await _read_with_counter(iam, engine, identity_id)
        assert result == _PROFILE
        assert selects == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_profile_save_invalidates_and_next_read_executes_sql(
    database_url: str, phi_enabled: None
) -> None:
    engine, iam = _build_iam(database_url)
    try:
        identity_id = await _seed_profile(iam)
        await iam.get_patient_profile(identity_id)
        _, cached_selects = await _read_with_counter(iam, engine, identity_id)
        assert cached_selects == 0

        await iam.save_patient_profile(identity_id, _UPDATED_PROFILE)

        await _assert_sql_read(iam, engine, identity_id, expected=_UPDATED_PROFILE)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_redis_miss_falls_back_to_sql(database_url: str, phi_enabled: None) -> None:
    engine, iam = _build_iam(database_url)
    try:
        identity_id = await _seed_profile(iam)

        await _assert_sql_read(iam, engine, identity_id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_redis_error_falls_back_to_sql(database_url: str, phi_enabled: None) -> None:
    engine, iam = _build_iam(database_url)
    try:
        with fake_redis_client(_ErrorRedis()):
            identity_id = await _seed_profile(iam)

            await _assert_sql_read(iam, engine, identity_id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        '{"name": "Broken Payload"}',
        "[1, 2, 3]",
    ],
)
async def test_malformed_or_incompatible_payload_is_a_miss(
    database_url: str, phi_enabled: None, fake_redis: FakeRedis, payload: str
) -> None:
    engine, iam = _build_iam(database_url)
    try:
        identity_id = await _seed_profile(iam)
        _seed_cached_payload(fake_redis, identity_id, payload)

        await _assert_sql_read(iam, engine, identity_id)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_phi_gate_blocks_cache_when_disabled_and_allows_when_enabled(
    database_url: str,
    phi_enabled: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, iam = _build_iam(database_url)
    try:
        identity_id = await _seed_profile(iam)

        # Gate open: first read executes SQL, second read is a warm cache hit.
        await _assert_sql_read(iam, engine, identity_id)
        _, warm_selects = await _read_with_counter(iam, engine, identity_id)
        assert warm_selects == 0

        # Gate closed: the warm entry is ignored and every read executes SQL.
        monkeypatch.setenv("PHI_CACHE_ENABLED", "false")
        await _assert_sql_read(iam, engine, identity_id)
        await _assert_sql_read(iam, engine, identity_id)
    finally:
        await engine.dispose()
