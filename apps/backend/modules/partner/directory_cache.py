"""MOD-002 Redis client for the directory-search result cache (PHASE-6 T02b, #314).

Optional Redis connection pool managed at app lifetime; gracefully degrades to
SQL-only when unavailable or misconfigured - the same optional-with-SQL-fallback
discipline as the consent-status cache (``consent/redis_cache.py``). Redis is an
accelerator ONLY, never a correctness surface (ADR-0011 lazy correctness): the
search facade re-derives partner validity from recorded dates on every read -
even on a cache hit - so a stale row for a deactivated or expired partner can
never surface.
"""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

import redis.asyncio as redis
from redis.asyncio import Redis

from app.config import Settings

_LOG = logging.getLogger(__name__)

_REDIS_CLIENT: Redis | None = None

# Cache key namespace for directory search results. Distinct from the consent
# namespace (``consent:*``) so the two caches never collide on the same server.
_DIRECTORY_NAMESPACE = "directory"


async def init_directory_redis_client(settings: Settings) -> None:
    """Initialize the global directory-search Redis client from settings.

    Called once at app startup from ``create_app``. If ``redis_url`` is empty
    or connection fails, the client stays ``None`` and all cache operations
    become no-ops (SQL fallback) - Redis down/absent is a degraded state, never
    an error path.
    """
    global _REDIS_CLIENT
    url = settings.redis_url.strip()
    if not url:
        _LOG.info("Redis URL not configured; directory cache disabled (SQL fallback)")
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
        await _REDIS_CLIENT.ping()
        _LOG.info("Redis directory cache connected")
    except Exception as exc:
        _LOG.warning("Redis directory cache unavailable (%s); falling back to SQL", exc)
        _REDIS_CLIENT = None


async def close_directory_redis_client() -> None:
    """Close the directory-search Redis connection pool at app shutdown."""
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        await _REDIS_CLIENT.close()
        _REDIS_CLIENT = None


def get_directory_redis_client() -> Redis | None:
    """Return the active directory-search Redis client, or ``None`` if unavailable.

    Callers MUST treat ``None`` as a cache miss and fall back to SQL.
    """
    return _REDIS_CLIENT


def _cache_key(
    *,
    query: str | None,
    partner_type: str | None,
    specialty: str | None,
    latitude: float,
    longitude: float,
    expanded: bool,
) -> str:
    """Build the cache key covering query, filters, geo and the expanded-area flag.

    ``expanded`` records whether the view was the wider-area (``fell_back``)
    variant - the peri-urban first pass and the relaxed second pass for the same
    query/filters/geo must never share a row (a narrow-area miss must not serve a
    wide-area payload, or vice versa).
    """
    parts = [
        _DIRECTORY_NAMESPACE,
        query or "",
        partner_type or "",
        specialty or "",
        f"{latitude:.6f}",
        f"{longitude:.6f}",
        "1" if expanded else "0",
    ]
    return ":".join(parts)


def _serialize(items: list[dict[str, Any]], fell_back: bool) -> str:
    return json.dumps({"items": items, "fell_back": fell_back})


def _deserialize(data: str) -> tuple[list[dict[str, Any]], bool] | None:
    try:
        payload = json.loads(data)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        return None
    return payload["items"], bool(payload.get("fell_back", False))


async def get_cached_search(
    *,
    query: str | None,
    partner_type: str | None,
    specialty: str | None,
    latitude: float,
    longitude: float,
    expanded: bool,
) -> tuple[list[dict[str, Any]], bool] | None:
    """Try to read a cached directory search view.

    Returns ``(raw_items, fell_back)`` on hit, ``None`` on miss or any Redis
    error (fail-open to SQL).
    """
    client = get_directory_redis_client()
    if client is None:
        return None
    key = _cache_key(
        query=query,
        partner_type=partner_type,
        specialty=specialty,
        latitude=latitude,
        longitude=longitude,
        expanded=expanded,
    )
    try:
        data = await client.get(key)
        if data is None:
            return None
        return _deserialize(data.decode() if isinstance(data, bytes) else data)
    except Exception:
        _LOG.debug("Redis directory cache read failed; SQL fallback will apply", exc_info=True)
        return None


async def set_cached_search(
    *,
    query: str | None,
    partner_type: str | None,
    specialty: str | None,
    latitude: float,
    longitude: float,
    expanded: bool,
    raw_items: list[dict[str, Any]],
    fell_back: bool,
    ttl_seconds: int,
) -> None:
    """Write a directory search view to the cache (best-effort, never blocks)."""
    client = get_directory_redis_client()
    if client is None:
        return
    key = _cache_key(
        query=query,
        partner_type=partner_type,
        specialty=specialty,
        latitude=latitude,
        longitude=longitude,
        expanded=expanded,
    )
    try:
        await client.set(key, _serialize(raw_items, fell_back), ex=ttl_seconds)
    except Exception:
        _LOG.debug("Redis directory cache write failed; SQL fallback will apply", exc_info=True)


async def invalidate_directory_cache() -> None:
    """Invalidate ALL directory search cache rows.

    Fired on ``partner.activated`` and ``credential.invalidated`` (the two
    events that can change which partners a cached search would return). Because
    search results are sets of partners and the key buckets query/filters/geo,
    no single partner can be addressed by key - the whole namespace is flushed.
    Best-effort: Redis down is a no-op, and lazy correctness on the read path
    keeps correctness regardless.
    """
    client = get_directory_redis_client()
    if client is None:
        return
    pattern = f"{_DIRECTORY_NAMESPACE}:*"
    with contextlib.suppress(Exception):
        cursor = 0
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await client.delete(*keys)
            if cursor == 0:
                break


async def directory_visibility_changed() -> None:
    """Flush the directory cache after any mutation that changes directory visibility.

    The single flush point every directory-visibility mutation (partner
    activation, credential invalidation on re-verification failure, immediate
    revocation, the daily expiry close-out pass, and the permanent-rejection
    purge) funnels through - a visibility change can never be forgotten at one
    spot. Wraps :func:`invalidate_directory_cache` unchanged: best-effort
    namespace flush, silent on Redis absence or failure.
    """
    await invalidate_directory_cache()
