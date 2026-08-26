# Brief - FIX-9 Deduplicate cache invalidation methods in ConsentFacade

**Ticket:** #229 · **Parent:** #209 · **Refreshed:** 2026-08-25
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

`_invalidate_cache_on_grant` and `_invalidate_cache_on_revoke` merged into single `_invalidate_cache` method. No middle-man indirection.

**Acceptance criteria:**

- Single `_invalidate_cache(patient_id, counterparty_type, counterparty_id, record_scope)` method in `ConsentFacade`
- Grant path calls `_invalidate_cache` directly
- Revoke path calls `_invalidate_cache` directly
- No other callers reference the old method names
- `npm run test:unit:backend` passes

## Read-list (in order)

1. `apps/backend/modules/consent/facade.py:798-821` - the two duplicate methods (~821 tokens total, read 798-821)
2. Grep for callers of `_invalidate_cache_on_grant` and `_invalidate_cache_on_revoke` in `facade.py`

**Total:** ~250 tokens of targeted reading, well within budget.

## Do NOT read

- Route code, frontend code
- Redis cache internals
- Standards docs

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - verify current state
- `grep -n "_invalidate_cache_on" apps/backend/modules/consent/facade.py` - confirm both methods exist

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` passes
- `grep -n "_invalidate_cache_on" apps/backend/modules/consent/facade.py` returns no matches
- `grep -n "_invalidate_cache" apps/backend/modules/consent/facade.py` shows single method definition

## Handoff notes

- Both methods have identical signatures, docstrings, and bodies (lines 799-821)
- They both call `invalidate_cached_decision(patient_id, counterparty_type, counterparty_id, record_scope)`
- The callers are in the grant and revoke methods - find them with grep
- Rename to `_invalidate_cache` and update both call sites
