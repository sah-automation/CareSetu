# Brief - PHASE-6-T02b Directory Search Result Cache

**Ticket:** #314 · **Parent:** #306 (split from #308) · **Refreshed:** 2026-09-05
**Reading surface:** ~3.5K tokens (budget 10K) - comfortably within budget

## Scope

Directory search results are cached in Redis to accelerate repeat searches, following the existing optional-with-SQL-fallback pattern. The cache is an accelerator only, never a correctness surface: a stale row for a deactivated/expired partner must never surface because the search read path re-derives validity from recorded dates (ADR-0011). Layers on top of the working search core (#313).

Acceptance criteria (from ticket):

- [ ] Cache module in the partner module (e.g. `directory_cache.py`) following `consent/redis_cache.py` optional-with-SQL-fallback pattern (client missing/failed -> silent SQL fallback, no error to caller)
- [ ] Cache key covers query, filters, geo, and expanded-area flag; TTL applied
- [ ] Cache invalidation hook fires on `partner.activated` and `credential.invalidated`
- [ ] Lazy correctness: facade never trusts the cache for the valid-credential tick - reads re-derive validity regardless of cache hit (ADR-0011)
- [ ] Tests: cache hit path, cache miss -> SQL fallback, invalidation on both events, stale-cache-never-surfaces

## Read-list (in order)

1. `apps/backend/modules/consent/redis_cache.py` - THE pattern to replicate (~167 lines): global singleton client, `init_redis_client` at startup pinging and degrading to `None`, `get_redis_client` returning `None` on failure, every read/write wrapped in try/except that silently falls back to SQL, key scheme `domain:...:...`. (~1K)
2. `app/config.py` - the redis settings the init reads. (~0.5K)
3. `docs/adr/0011-credential-expiry-lazy-daily-sweep.md` - the lazy correctness rule: cache never decides visibility; the read path re-derives the tick from activation + credential dates. (~1.5K)
4. `apps/backend/bus/events.py` - locate the `partner.activated` and `credential.invalidated` event constants and how the facade's write path emits them, to place the invalidation hook. (~0.5K)
5. Closing comment of #313 - the search facade surface + cache seam this wraps.

## Do NOT read

- Frontend code, notify module, IAM module internals, facade write internals beyond the invalidation hook, `docs/archive/`, other ADRs.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASSED 2026-09-05
- `npm run test:unit:backend` - PASSED 2026-09-05 (1211 passed)

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run test:integration` (needs local Postgres; skips if unreachable)

## Handoff notes

- Redis unavailability is a degraded-state, never an error path - match the consent module's silent degradation exactly.
- Cache key must include the expanded-area flag, otherwise a narrow-area miss could serve a wide-area payload (or vice versa).
- Tests assert external behavior (which results come back, invalidation happens, stale never surfaces) - not cache internals.
- Blocked by #313 - starts once the search core lands.
