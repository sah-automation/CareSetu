"""In-process atomic flags for runtime toggles (ticket #895).

These flags are flipped by the cache module's handler for
``ops.runtime_setting_changed`` events, and read by cache/redis helpers
to apply toggles without restart (threading.Event for atomic cross-thread reads).
"""

from __future__ import annotations

import os
import threading

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


def _env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in _TRUE_VALUES


def _seed_redis_enabled() -> bool:
    env_value = os.environ.get("REDIS_ENABLED")
    if env_value is not None:
        return env_value.strip().lower() in _TRUE_VALUES
    return bool(os.environ.get("REDIS_URL", "").strip())


# Atomic flags for runtime toggles (threading.Event, atomic cross-thread reads).
# Seeded from the environment at import so a booted process reflects the env-driven
# defaults without waiting for an outbox event (#895).
_cache_enabled_flag: threading.Event = threading.Event()
if _env_flag("CACHE_ENABLED", True):
    _cache_enabled_flag.set()

_redis_enabled_flag: threading.Event = threading.Event()
if _seed_redis_enabled():
    _redis_enabled_flag.set()


def cache_enabled() -> bool:
    """Return True if cache is currently enabled (atomic read)."""
    return _cache_enabled_flag.is_set()


def redis_enabled() -> bool:
    """Return True if redis is currently enabled (atomic read)."""
    return _redis_enabled_flag.is_set()


def set_cache_enabled(value: bool) -> None:
    """Set the cache enabled flag."""
    if value:
        _cache_enabled_flag.set()
    else:
        _cache_enabled_flag.clear()


def set_redis_enabled(value: bool) -> None:
    """Set the redis enabled flag."""
    if value:
        _redis_enabled_flag.set()
    else:
        _redis_enabled_flag.clear()


__all__ = [
    "cache_enabled",
    "redis_enabled",
    "set_cache_enabled",
    "set_redis_enabled",
]
