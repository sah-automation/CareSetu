"""MOD-004 Redis client for consent-status cache (PHASE-3 T4, #213).

Delegates to the shared application-owned Redis client (ARCH-P1 #812).
Optional Redis connection pool managed at app lifetime; gracefully degrades
to SQL-only when unavailable or misconfigured.
"""

from __future__ import annotations

import contextlib
import logging

from app.redis import close_redis_client, get_redis_client, init_redis_client

__all__ = [
    "close_redis_client",
    "get_cached_decision",
    "get_redis_client",
    "init_redis_client",
    "invalidate_all_for_patient",
    "invalidate_cached_decision",
    "set_cached_decision",
]
from observability.otel import record_cache_hit, record_cache_miss

_LOG = logging.getLogger(__name__)


def _cache_key(
    patient_id: int, counterparty_type: str, counterparty_id: str, record_scope: str
) -> str:
    """Build the cache key: patient+scope+counterparty (brief)."""
    return f"consent:{patient_id}:{record_scope}:{counterparty_type}:{counterparty_id}"


async def get_cached_decision(
    patient_id: int,
    counterparty_type: str,
    counterparty_id: str,
    record_scope: str,
) -> tuple[bool, int, int, str] | None:
    """Try to read a cached consent decision.

    Returns ``(allowed, consent_id, version, effective_scope)`` on hit,
    ``None`` on miss or any Redis error (fail-closed -> SQL fallback).
    """
    client = get_redis_client()
    if client is None:
        record_cache_miss("consent")
        return None
    key = _cache_key(patient_id, counterparty_type, counterparty_id, record_scope)
    try:
        data = await client.hmget(key, ["allowed", "consent_id", "version", "effective_scope"])
        if data[0] is None:
            record_cache_miss("consent")
            return None
        allowed = data[0] == "1"
        consent_id = int(data[1] or 0)
        version = int(data[2] or 0)
        effective_scope = str(data[3] or "")
    except Exception:
        record_cache_miss("consent")
        _LOG.debug("Redis cache read failed; SQL fallback will apply", exc_info=True)
        return None
    record_cache_hit("consent")
    return (allowed, consent_id, version, effective_scope)


async def set_cached_decision(
    patient_id: int,
    counterparty_type: str,
    counterparty_id: str,
    record_scope: str,
    allowed: bool,
    consent_id: int,
    version: int,
    effective_scope: str,
    ttl_seconds: int,
) -> None:
    """Write a consent decision to the cache (best-effort, never blocks)."""
    client = get_redis_client()
    if client is None:
        return
    key = _cache_key(patient_id, counterparty_type, counterparty_id, record_scope)
    try:
        await client.hset(
            key,
            mapping={
                "allowed": "1" if allowed else "0",
                "consent_id": str(consent_id),
                "version": str(version),
                "effective_scope": effective_scope,
            },
        )
        await client.expire(key, ttl_seconds)
    except Exception:
        _LOG.debug("Redis cache write failed; SQL fallback will apply", exc_info=True)


async def invalidate_cached_decision(
    patient_id: int,
    counterparty_type: str,
    counterparty_id: str,
    record_scope: str,
) -> None:
    """Invalidate a single cached decision (grant/revoke hook)."""
    client = get_redis_client()
    if client is None:
        return
    key = _cache_key(patient_id, counterparty_type, counterparty_id, record_scope)
    try:
        await client.delete(key)
    except Exception:
        _LOG.debug("Redis cache invalidation failed", exc_info=True)


async def invalidate_all_for_patient(patient_id: int) -> None:
    """Invalidate all cached decisions for a patient (broad sweep)."""
    client = get_redis_client()
    if client is None:
        return
    pattern = f"consent:{patient_id}:*"
    with contextlib.suppress(Exception):
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await client.delete(*keys)
            if cursor == 0:
                break
