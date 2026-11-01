"""Unit tests for the shared read-cache foundation (ARCH-P1 #816)."""

from __future__ import annotations

import json
from typing import Any

import pytest

import app.redis as shared_redis
from app.cache import (
    CacheNamespace,
    get_cached,
    invalidate,
    phi_cache_enabled,
    set_cached,
)
from app.config import Settings


class _FakeRedis:
    def __init__(self, store: dict[str, str] | None = None) -> None:
        self.store: dict[str, str] = store if store is not None else {}
        self.ttls: dict[str, int | None] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value
        self.ttls[key] = ex

    async def scan(
        self, cursor: int = 0, match: str | None = None, count: int | None = None
    ) -> tuple[int, list[str]]:
        keys = (
            sorted(self.store)
            if match is None
            else [k for k in self.store if k.startswith(match.rstrip("*"))]
        )
        return 0, keys

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self.store:
                del self.store[key]
                removed += 1
        return removed

    async def ttl(self, key: str) -> int:
        return -1 if self.ttls.get(key) is None else int(self.ttls[key] or 0)


@pytest.fixture(autouse=True)
def _reset_redis_client() -> Any:
    yield
    shared_redis._REDIS_CLIENT = None


def _client(store: dict[str, str] | None = None) -> _FakeRedis:
    client = _FakeRedis(store)
    shared_redis._REDIS_CLIENT = client
    return client


async def test_get_returns_none_when_client_none() -> None:
    shared_redis._REDIS_CLIENT = None
    assert await get_cached(None, "ns", "k") is None


async def test_hit_miss_round_trip() -> None:
    store: dict[str, str] = {}
    client = _client(store)
    await set_cached(client, "ns", "k", {"x": 1}, ttl_seconds=10)
    assert await get_cached(client, "ns", "k") == {"x": 1}
    assert await get_cached(client, "ns", "miss") is None


async def test_malformed_payload_is_miss() -> None:
    store: dict[str, str] = {}
    client = _client(store)
    store["ns:bad"] = "not-json{"
    assert await get_cached(client, "ns", "bad") is None


async def test_redis_error_is_miss() -> None:
    class _Failing(_FakeRedis):
        async def get(self, key: str) -> str | None:  # type: ignore[override]
            raise RuntimeError("boom")

    client = _Failing()
    shared_redis._REDIS_CLIENT = client
    assert await get_cached(client, "ns", "k") is None


async def test_ttl_pass_through() -> None:
    store: dict[str, str] = {}
    client = _client(store)
    await set_cached(client, "ns", "k", 1, ttl_seconds=42)
    assert client.ttls["ns:k"] == 42


async def test_degraded_cap_write() -> None:
    store: dict[str, str] = {}
    client = _client(store)
    settings = Settings(degraded_mode=True, degraded_cache_ttl_seconds=5, redis_url="redis://x")
    await set_cached(
        client,
        "ns",
        "k",
        1,
        ttl_seconds=100,
        settings=settings,
        degraded_mode=True,
        degraded_cache_ttl_seconds=5,
    )
    assert client.ttls["ns:k"] == 5


async def test_degraded_cap_read() -> None:
    store: dict[str, str] = {}
    client = _client(store)
    await set_cached(client, "ns", "k", 1, ttl_seconds=100)
    # cap lower than remaining -> miss
    settings = Settings(degraded_mode=True, degraded_cache_ttl_seconds=5, redis_url="redis://x")
    assert (
        await get_cached(
            client,
            "ns",
            "k",
            degraded_mode=True,
            degraded_cache_ttl_seconds=5,
            settings=settings,
        )
        is None
    )


async def test_phi_gate() -> None:
    settings_disabled = Settings(phi_cache_enabled=False, redis_url="redis://x")
    settings_enabled = Settings(phi_cache_enabled=True, redis_url="redis://x")
    assert phi_cache_enabled(None, settings_enabled) is False
    shared_redis._REDIS_CLIENT = None
    # configured via redis_url only when no client explicitly passed
    assert phi_cache_enabled(settings_enabled) is True
    assert phi_cache_enabled(settings_disabled) is False
    # gate disables read when phi cache not allowed
    store: dict[str, str] = {}
    redis_client = _FakeRedis(store)
    await set_cached(redis_client, "profile", "k", 1, ttl_seconds=10, phi=True)
    # Without enabling phi, profile read is not attempted as cached hit? With gate we record miss.
    shared_redis._REDIS_CLIENT = redis_client
    assert await get_cached(redis_client, "profile", "k", phi=True) is None


async def test_invalidation() -> None:
    store: dict[str, str] = {}
    client = _client(store)
    await set_cached(client, "ns", "k", 1, ttl_seconds=10)
    await invalidate(client, "ns")
    assert await get_cached(client, "ns", "k") is None
    assert "ns:k" not in store


async def test_namespace_descriptor() -> None:
    ns = CacheNamespace("ns", ttl_seconds=7, phi=True)
    assert str(ns) == "ns"
    assert ns.ttl_seconds == 7
    assert ns.phi is True
    assert json.loads('{"a": 1}') == {"a": 1}
