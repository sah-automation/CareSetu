"""``idempotency`` in-process store for the auth mutations (PHASE-2 REM T11, #80).

api-standards §5: mutations accept an ``Idempotency-Key`` header and a duplicate
key returns the original result without re-executing the mutation - so a client
retry after a network failure cannot double-issue an OTP or double-consume a
challenge. The contract sits at the edge, not in MOD-001: the store is a thin
gateway concern keyed by request path + client key, and the module facade never
sees it (internal-modules §3.1/§4.1).

The memory discipline mirrors ``RateLimitMiddleware`` exactly: a monotonic-clock
TTL per key and a bounded dict with prune-then-evict under a key spray, so an
attacker spraying fresh keys cannot grow the dict without bound. In-process per
process by design - a process restart loses every entry and degrades to
at-most-once for the retried request, an accepted, documented trade-off for this
phase (the same posture the rate limiter takes). Deduplication therefore holds
for sequential replays of a completed mutation; two simultaneous in-flight
copies of the same key (the request racing its own retry) can both reach the
facade, which is exactly the non-locking behaviour of the rate limiter and is
kept deliberate here.
"""

from __future__ import annotations

import time
from collections.abc import Callable

# Entry TTL mirrors the OTP challenge lifetime (MOD-001 §3.1): a client retry
# after a lost response needs the stored result for at least the window in which
# the issued challenge stays usable.
_DEFAULT_TTL_SECONDS = 300
# Upper bound on tracked keys: once exceeded, expired entries are pruned and, if
# the dict is still over the cap, the oldest live entries are evicted so a key
# spray cannot grow the dict without bound (mirrors ``_MAX_TRACKED_BUCKETS``).
_MAX_TRACKED_KEYS = 1024


class IdempotencyStore:
    """In-process idempotency result cache for the OTP/auth mutations.

    ``get`` returns a previously stored result while the key is live and drops
    the entry once its TTL has elapsed; ``put`` records a completed mutation's
    result under the key and keeps the dict bounded. ``clock`` is injectable so
    tests can drive TTL expiry without sleeping.
    """

    def __init__(
        self,
        *,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        max_entries: int = _MAX_TRACKED_KEYS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: dict[str, tuple[float, object]] = {}

    def get(self, key: str) -> object | None:
        """The stored result for ``key`` while it is live, else ``None``.

        A read of an expired entry drops it lazily (``put`` and ``_prune``
        sweep the rest), so a key replayed after its TTL behaves like a fresh
        key.
        """
        now = self._clock()
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at <= now:
            del self._entries[key]
            return None
        return value

    def put(self, key: str, value: object) -> None:
        """Record ``value`` as the completed result for ``key``."""
        now = self._clock()
        self._entries[key] = (now + self._ttl_seconds, value)
        if len(self._entries) > self._max_entries:
            self._prune(now)

    def _prune(self, now: float) -> None:
        """Keep the entry dict bounded under a key spray.

        First drop entries whose TTL has closed; if the dict is still over the
        cap, evict the oldest live entries too. Under pressure the store forgets
        the oldest results rather than grow without bound - the sprayer's keys
        being evicted is exactly the trade-off that keeps memory flat (mirrors
        ``RateLimitMiddleware._prune``).
        """
        expired = [key for key, (expires_at, _) in self._entries.items() if expires_at <= now]
        for key in expired:
            del self._entries[key]

        over = len(self._entries) - self._max_entries
        if over > 0:
            oldest = sorted(self._entries, key=lambda key: self._entries[key][0])[:over]
            for key in oldest:
                del self._entries[key]
