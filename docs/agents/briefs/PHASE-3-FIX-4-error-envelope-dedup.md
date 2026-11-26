# Brief - FIX-4 Deduplicate ErrorEnvelope across adapter modules

**Ticket:** #224 · **Parent:** #209 · **Refreshed:** 2026-08-25
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

Single `ErrorEnvelope` model shared by all three adapter modules (consent, health, iam). Currently duplicated in three files.

**Acceptance criteria:**

- Shared `ErrorEnvelope` model lives in `app/gateway/errors.py` (or new `app/gateway/envelope.py`)
- `modules/consent/adapters/routes.py` imports from shared location, removes local definition
- `modules/health/adapters/routes.py` imports from shared location, removes local definition
- `modules/iam/adapters/routes.py` imports from shared location, removes local definition
- `npm run typecheck` passes
- `npm run test:unit:backend` passes

## Read-list (in order)

1. `apps/backend/app/gateway/errors.py` - existing shared error codes and `error_response` function (~80 tokens)
2. `apps/backend/modules/consent/adapters/routes.py:40-46` - local `ErrorEnvelope` definition to remove (~47 tokens)
3. `apps/backend/modules/health/adapters/routes.py:38-44` - local `ErrorEnvelope` definition to remove (~174 tokens)
4. `apps/backend/modules/iam/adapters/routes.py` - search for `ErrorEnvelope` import/definition (~408 tokens)

**Total:** ~700 tokens of reading, well within budget.

## Do NOT read

- Facade code, frontend code
- Other adapter modules
- Standards docs

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - verify current state
- `grep -rn "class ErrorEnvelope" apps/backend/modules/` - confirm three definitions exist

## Done-verify (acceptance criteria → commands)

- `npm run typecheck` passes
- `npm run test:unit:backend` passes
- `grep -rn "class ErrorEnvelope" apps/backend/modules/` returns no matches (only in gateway)

## Handoff notes

- The `ErrorEnvelope` in `iam/adapters/routes.py` is imported by `app/main.py` line 41 - check if main.py imports it from iam or defines its own
- The shared model should have: `code: str`, `message: str`, `trace_id: str`, `details: dict[str, object]`
- All three modules use the same shape - just move one to `app/gateway/errors.py` and update imports
- The `error_response` function in `app/gateway/errors.py` already uses a similar envelope - check if it can be reused or if a separate model is needed
