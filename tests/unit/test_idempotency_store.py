"""PHASE-2 REM T11 (#80): the gateway idempotency store.

The store is the edge's in-process dedupe for the auth mutations (api-standards
§5): a completed result is kept under its ``Idempotency-Key`` for the TTL and a
replay reads it back; entries expire after the TTL and the dict stays bounded
under a key spray, mirroring ``RateLimitMiddleware``'s prune-then-evict
discipline. A clock is injected so TTL expiry is driven by the test, not the
wall clock.
"""

from __future__ import annotations

from app.gateway.idempotency import (
    _MAX_TRACKED_KEYS,
    IdempotencyStore,
)


def test_put_then_get_returns_the_stored_result(fake_clock) -> None:
    store = IdempotencyStore(clock=fake_clock)

    store.put("key-1", {"outcome": "sent"})

    assert store.get("key-1") == {"outcome": "sent"}


def test_get_unknown_key_returns_none(fake_clock) -> None:
    store = IdempotencyStore(clock=fake_clock)

    assert store.get("never-put") is None


def test_put_same_key_overwrites_with_the_latest_result(fake_clock) -> None:
    store = IdempotencyStore(clock=fake_clock)
    store.put("key-1", {"outcome": "sent"})

    store.put("key-1", {"outcome": "cooldown"})

    assert store.get("key-1") == {"outcome": "cooldown"}


def test_entry_expires_after_the_ttl(fake_clock) -> None:
    store = IdempotencyStore(ttl_seconds=300, clock=fake_clock)
    store.put("key-1", {"outcome": "sent"})
    fake_clock.advance(300)

    assert store.get("key-1") is None


def test_entry_survives_until_the_ttl_boundary(fake_clock) -> None:
    store = IdempotencyStore(ttl_seconds=300, clock=fake_clock)
    store.put("key-1", {"outcome": "sent"})
    fake_clock.advance(299.999)

    assert store.get("key-1") == {"outcome": "sent"}


def test_expired_entry_is_dropped_on_read(fake_clock) -> None:
    store = IdempotencyStore(ttl_seconds=300, clock=fake_clock)
    store.put("key-1", {"outcome": "sent"})
    fake_clock.advance(301)
    assert store.get("key-1") is None

    assert store.get("key-1") is None
    assert len(store._entries) == 0


def test_prune_drops_expired_entries_and_keeps_the_dict_bounded(
    fake_clock,
) -> None:
    store = IdempotencyStore(ttl_seconds=300, max_entries=_MAX_TRACKED_KEYS, clock=fake_clock)
    now = fake_clock()
    for index in range(_MAX_TRACKED_KEYS + 50):
        store._entries[f"spray-{index}"] = (now + 300, {"outcome": "sent"})
    # Age the oldest 50 past the TTL so pruning can reclaim them.
    for index in range(50):
        store._entries[f"spray-{index}"] = (now + 0, {"outcome": "sent"})

    store._prune(now + 1)

    assert len(store._entries) <= _MAX_TRACKED_KEYS
    assert all(f"spray-{index}" not in store._entries for index in range(50))


def test_put_after_ttl_starts_a_fresh_lifetime(fake_clock) -> None:
    store = IdempotencyStore(ttl_seconds=300, clock=fake_clock)
    store.put("key-1", {"outcome": "sent"})
    fake_clock.advance(301)
    assert store.get("key-1") is None

    store.put("key-1", {"outcome": "sent"})
    fake_clock.advance(299)

    assert store.get("key-1") == {"outcome": "sent"}
