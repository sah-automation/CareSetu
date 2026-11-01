"""Shared application-owned async Redis client (ARCH-P1 #812).

Single client initialized once at startup, pinged, and closed at shutdown.
Empty REDIS_URL creates no client. Unreachable Redis logs a non-fatal warning
and leaves all cache callers on SQL fallback.
"""

from __future__ import annotations

import logging

import redis.asyncio as redis
from redis.asyncio import Redis

from app.config import Settings

_LOG = logging.getLogger(__name__)

_REDIS_CLIENT: Redis | None = None


async def init_redis_client(settings: Settings) -> None:
    """Initialize the global shared Redis client from settings.

    Called once at app startup from the lifespan. If redis_url is empty or
    connection fails, the client stays None and all cache operations become
    no-ops (SQL fallback).
    """
    global _REDIS_CLIENT
    url = settings.redis_url.strip()
    if not url:
        _LOG.info("Redis URL not configured; shared cache disabled (SQL fallback)")
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
        _LOG.info("Redis shared cache connected")
    except Exception as exc:
        _LOG.warning("Redis shared cache unavailable (%s); falling back to SQL", exc)
        _REDIS_CLIENT = None


async def close_redis_client() -> None:
    """Close the Redis connection pool at app shutdown."""
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        await _REDIS_CLIENT.close()
        _REDIS_CLIENT = None


def get_redis_client() -> Redis | None:
    """Return the active shared Redis client, or None if unavailable.

    Callers MUST treat None as a cache miss and fall back to SQL.
    """
    return _REDIS_CLIENT
