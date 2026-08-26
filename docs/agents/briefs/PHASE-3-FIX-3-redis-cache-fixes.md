# Brief - FIX-3 Fix Redis cache logging and error handling

**Ticket:** #223 · **Parent:** #209 · **Refreshed:** 2026-08-25
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

Redis connection URL is no longer logged at INFO level, and cache read/write failures log at debug level instead of being silently swallowed.

**Acceptance criteria:**

- `redis_cache.py:47` no longer logs any part of the Redis URL
- `get_cached_decision` (line ~101) logs at debug level before returning None on exception
- `invalidate_cached_decision` (line ~147) logs at debug level instead of using `contextlib.suppress(Exception)`
- `set_cached_decision` (line ~132) already logs - verify it uses debug level
- Unit tests pass: `npm run test:unit:backend`

## Read-list (in order)

1. `apps/backend/modules/consent/redis_cache.py` - full file, 164 lines (~164 tokens)

**Total:** ~164 tokens of reading, well within budget.

## Do NOT read

- Facade code, route code, frontend code
- Redis configuration in `app/config.py`
- Standards docs

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - current state: timed out in session, may need longer timeout

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` passes
- `grep -n "split.*@" apps/backend/modules/consent/redis_cache.py` returns no matches
- `grep -n "suppress(Exception)" apps/backend/modules/consent/redis_cache.py` returns no matches

## Handoff notes

- Line 47: `_LOG.info("Redis consent cache connected: %s", url.split("@")[-1]...)` - change to `_LOG.info("Redis consent cache connected")`
- Line 101: `except Exception: return None` - add `_LOG.debug("Redis cache read failed; SQL fallback", exc_info=True)` before return
- Line 147: `with contextlib.suppress(Exception):` - replace with try/except that logs at debug level
- Line 132: `except Exception: _LOG.debug(...)` - already correct, no change needed
- The `contextlib` import may become unused after the fix - remove if so
