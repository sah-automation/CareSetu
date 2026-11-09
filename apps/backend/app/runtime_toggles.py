"""In-process atomic flags for runtime toggles (ticket #895).

These flags are flipped by the cache module's handler for
``ops.runtime_setting_changed`` events, and read by cache/redis helpers
to apply toggles without restart (threading.Event for atomic cross-thread reads).
"""

from __future__ import annotations

import threading

# Atomic flags for runtime toggles (threading.Event, atomic cross-thread reads).
# Default to True (cache enabled, redis enabled) so existing behavior is preserved
# until an event flips them.
_cache_enabled_flag: threading.Event = threading.Event()
_cache_enabled_flag.set()

_redis_enabled_flag: threading.Event = threading.Event()
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
