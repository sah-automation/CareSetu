"""MOD-004 Redis client for consent-status cache (PHASE-3 T4, #213).

Optional Redis connection pool managed at app lifetime; gracefully degrades
to SQL-only when unavailable or misconfigured. No hard dependency on Redis
so local/integration tiers stay simple (brief: "No Redis client exists
anywhere in the backend yet - this ticket introduces the dependency").
"""

from __future__ import annotations

import contextlib
import logging

import redis.asyncio as redis
from redis.asyncio import Redis

from app.config import Settings

_LOG = logging.getLogger(__name__)

_REDIS_CLIENT: Redis | None = None


async def init_redis_client(settings: Settings) -> None:
    """Initialize the global Redis client from settings.

    Called once at app startup from ``create_app``. If ``redis_url`` is
    empty or connection fails, the client stays ``None`` and all cache
    operations become no-ops (SQL fallback).
    """
    global _REDIS_CLIENT
    url = settings.redis_url.strip()
    if not url:
        _LOG.info("Redis URL not configured; consent cache disabled (SQL fallback)")
        return
    try:
        _REDIS_CLIENT = redis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            max_connections=10,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        # Verify connectivity with a lightweight ping
        await _REDIS_CLIENT.ping()
        _LOG.info("Redis consent cache connected")
    except Exception as exc:
        _LOG.warning("Redis consent cache unavailable (%s); falling back to SQL", exc)
        _REDIS_CLIENT = None


async def close_redis_client() -> None:
    """Close the Redis connection pool at app shutdown."""
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        await _REDIS_CLIENT.close()
        _REDIS_CLIENT = None


def get_redis_client() -> Redis | None:
    """Return the active Redis client, or ``None`` if unavailable.

    Callers MUST treat ``None`` as a cache miss and fall back to SQL.
    """
    return _REDIS_CLIENT


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
        return None
    key = _cache_key(patient_id, counterparty_type, counterparty_id, record_scope)
    try:
        data = await client.hmget(key, ["allowed", "consent_id", "version", "effective_scope"])
        if data[0] is None:
            return None
        return (
            data[0] == "1",
            int(data[1] or 0),
            int(data[2] or 0),
            str(data[3] or ""),
        )
    except Exception:
        _LOG.debug("Redis cache read failed; SQL fallback will apply", exc_info=True)
        return None


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
