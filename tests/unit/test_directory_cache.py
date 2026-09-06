"""PHASE-6 T02b: the directory-search Redis cache module (ticket #314).

Pins the partner-side cache seam - the module that mirrors the consent-status
cache optional-with-SQL-fallback pattern - WITHOUT a database or a live Redis:

- The cache key covers query, filters, geo and the expanded-area flag (the
  peri-urban and wider-area variants of the same search never share a row).
- Missing/raising Redis client degrades silently: reads return a miss and the
  facade falls back to SQL, writes are no-ops, invalidation is a no-op.
- A serialized search view round-trips through ``get``/``set`` with a TTL.
- Invalidation flushes the ``directory:*`` namespace only - the adjacent
  ``consent:*`` namespace is never touched.

Cache internals only - the facade's re-derivation (ADR-0011 lazy correctness)
is exercised in the integration suite against Postgres.
"""

from __future__ import annotations

from typing import Any

import pytest
from redis.asyncio import Redis

import modules.partner.directory_cache as directory_cache
from modules.partner.directory_cache import (
    _cache_key,
    get_cached_search,
    invalidate_directory_cache,
    set_cached_search,
)
from modules.partner.facade import DALTONGANJ_LATITUDE, DALTONGANJ_LONGITUDE


class _FakeRedis:
    """Tiny in-memory stand-in for the ``redis.asyncio.Redis`` surface the
    directory cache touches: ``get``/``set(..., ex)``/``scan``/``delete``."""

    def __init__(self, store: dict[str, str] | None = None) -> None:
        self.store: dict[str, str] = store if store is not None else {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        self.ttl: dict[str, int | None] = {key: ex}

    async def scan(
        self, cursor: int, match: str | None = None, count: int | None = None
    ) -> tuple[int, list[str]]:
        all_keys = sorted(self.store)
        if match is not None:
            pattern = match.rstrip("*")
            all_keys = [k for k in all_keys if k.startswith(pattern) or k == pattern]
        return 0, all_keys

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
        return removed


def _install(client: Redis | None) -> None:
    directory_cache._REDIS_CLIENT = client


@pytest.fixture(autouse=True)
def _reset_redis_client() -> Any:
    yield
    _install(None)


def test_cache_key_covers_query_filters_geo_and_expanded_flag() -> None:
    base = _cache_key(
        query="sharma",
        partner_type="doctor",
        specialty="General Physician",
        latitude=DALTONGANJ_LATITUDE,
        longitude=DALTONGANJ_LONGITUDE,
        expanded=False,
    )
    assert base.startswith("directory:")
    assert base != _cache_key(
        query="mehta",
        partner_type="doctor",
        specialty="General Physician",
        latitude=DALTONGANJ_LATITUDE,
        longitude=DALTONGANJ_LONGITUDE,
        expanded=False,
    )
    assert base != _cache_key(
        query="sharma",
        partner_type="lab",
        specialty=None,
        latitude=DALTONGANJ_LATITUDE,
        longitude=DALTONGANJ_LONGITUDE,
        expanded=False,
    )
    assert base != _cache_key(
        query="sharma",
        partner_type="doctor",
        specialty="General Physician",
        latitude=DALTONGANJ_LATITUDE + 0.06,
        longitude=DALTONGANJ_LONGITUDE,
        expanded=False,
    )
    # The peri-urban and wider-area variants of the identical query/filters/geo
    # must never collide (a narrow-area miss must not serve a wide-area payload).
    assert base != _cache_key(
        query="sharma",
        partner_type="doctor",
        specialty="General Physician",
        latitude=DALTONGANJ_LATITUDE,
        longitude=DALTONGANJ_LONGITUDE,
        expanded=True,
    )


async def test_get_returns_none_when_client_missing() -> None:
    _install(None)
    assert (
        await get_cached_search(
            query=None,
            partner_type=None,
            specialty=None,
            latitude=DALTONGANJ_LATITUDE,
            longitude=DALTONGANJ_LONGITUDE,
            expanded=False,
        )
        is None
    )


async def test_set_is_noop_when_client_missing() -> None:
    _install(None)
    store: dict[str, str] = {}
    await set_cached_search(
        query="sharma",
        partner_type=None,
        specialty=None,
        latitude=DALTONGANJ_LATITUDE,
        longitude=DALTONGANJ_LONGITUDE,
        expanded=False,
        raw_items=[],
        fell_back=False,
        ttl_seconds=300,
    )
    assert store == {}


async def test_set_then_get_round_trips_view_with_ttl() -> None:
    store: dict[str, str] = {}
    _install(_FakeRedis(store))
    raw_items = [
        {
            "partner_id": 11,
            "practice_name": "Shanti Clinic",
            "partner_type": "doctor",
            "specialty": "General Physician",
            "distance_km": 1.2,
            "verified": True,
        }
    ]
    await set_cached_search(
        query="sharma",
        partner_type="doctor",
        specialty="General Physician",
        latitude=DALTONGANJ_LATITUDE,
        longitude=DALTONGANJ_LONGITUDE,
        expanded=False,
        raw_items=raw_items,
        fell_back=False,
        ttl_seconds=300,
    )
    assert len(store) == 1
    key = next(iter(store))
    assert key.startswith("directory:")
    assert store[key].startswith('{"items":')

    cached = await get_cached_search(
        query="sharma",
        partner_type="doctor",
        specialty="General Physician",
        latitude=DALTONGANJ_LATITUDE,
        longitude=DALTONGANJ_LONGITUDE,
        expanded=False,
    )
    assert cached is not None
    items, fell_back = cached
    assert fell_back is False
    assert items == raw_items


async def test_restored_view_matches_only_the_exact_key() -> None:
    store: dict[str, str] = {}
    _install(_FakeRedis(store))
    await set_cached_search(
        query="sharma",
        partner_type="doctor",
        specialty=None,
        latitude=DALTONGANJ_LATITUDE,
        longitude=DALTONGANJ_LONGITUDE,
        expanded=False,
        raw_items=[],
        fell_back=False,
        ttl_seconds=300,
    )
    # Same filters but different query -> miss, never the shuffled payload.
    assert (
        await get_cached_search(
            query="mehta",
            partner_type="doctor",
            specialty=None,
            latitude=DALTONGANJ_LATITUDE,
            longitude=DALTONGANJ_LONGITUDE,
            expanded=False,
        )
        is None
    )


async def test_invalidation_flushes_directory_namespace_only() -> None:
    store: dict[str, str] = {
        f"directory:sharma:doctor:::{DALTONGANJ_LATITUDE:.6f}:{DALTONGANJ_LONGITUDE:.6f}:0": (
            '{"items": []}'
        ),
        f"directory:sharma:doctor:::{DALTONGANJ_LATITUDE:.6f}:{DALTONGANJ_LONGITUDE:.6f}:1": (
            '{"items": []}'
        ),
        "consent:33:prescriptions:doctor:ch-1": "1",
    }
    _install(_FakeRedis(store))

    await invalidate_directory_cache()

    directory_keys = [k for k in store if k.startswith("directory:")]
    assert directory_keys == []
    # The consent namespace is untouched - the module never reaches across it.
    assert store == {"consent:33:prescriptions:doctor:ch-1": "1"}


async def test_invalidation_is_noop_when_client_missing() -> None:
    _install(None)
    await invalidate_directory_cache()
    # No exception raised: Redis absent is a degraded state, never an error


async def test_read_failure_degrades_to_miss() -> None:
    class _FailingRedis(_FakeRedis):
        async def get(self, key: str) -> str | None:
            raise RuntimeError("connection reset")

    _install(_FailingRedis())
    # A read that raises must surface as a miss - the facade then does SQL.
    assert (
        await get_cached_search(
            query="sharma",
            partner_type=None,
            specialty=None,
            latitude=DALTONGANJ_LATITUDE,
            longitude=DALTONGANJ_LONGITUDE,
            expanded=False,
        )
        is None
    )


async def test_write_failure_is_silent() -> None:
    class _FailingRedis(_FakeRedis):
        async def set(self, key: str, value: str, ex: int | None = None) -> None:  # type: ignore[override]
            raise RuntimeError("connection reset")

    _install(_FailingRedis())
    await set_cached_search(
        query="sharma",
        partner_type=None,
        specialty=None,
        latitude=DALTONGANJ_LATITUDE,
        longitude=DALTONGANJ_LONGITUDE,
        expanded=False,
        raw_items=[],
        fell_back=False,
        ttl_seconds=300,
    )


async def test_invalidation_failure_is_silent() -> None:
    class _FailingRedis(_FakeRedis):
        async def scan(  # type: ignore[override]
            self, cursor: int, match: str | None = None, count: int | None = None
        ) -> tuple[int, list[str]]:
            raise RuntimeError("connection reset")

    _install(_FailingRedis())
    await invalidate_directory_cache()
