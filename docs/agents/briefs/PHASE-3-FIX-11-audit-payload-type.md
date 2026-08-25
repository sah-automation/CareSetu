# Brief - FIX-11 Type ConsentAuditPayload.action as Literal

**Ticket:** #231 · **Parent:** #209 · **Refreshed:** 2026-08-25
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

`ConsentAuditPayload.action` changed from `str` to `Literal["requested", "granted", "revoked", "declined"]`.

**Acceptance criteria:**

- `ConsentAuditPayload.action` type is `Literal["requested", "granted", "revoked", "declined"]`
- All callers pass only values from the literal (grep to verify)
- `npm run typecheck` passes
- `npm run test:unit:backend` passes

## Read-list (in order)

1. `apps/backend/modules/consent/domain/events.py:77-91` - `ConsentAuditPayload` class (~191 tokens total)
2. Grep for all call sites that create `ConsentAuditPayload` in `consent/facade.py`

**Total:** ~250 tokens of reading, well within budget.

## Do NOT read

- Route code, frontend code
- Redis cache code
- Standards docs

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - verify current state
- `grep -rn "ConsentAuditPayload" apps/backend/modules/` - confirm all call sites

## Done-verify (acceptance criteria → commands)

- `npm run typecheck` passes
- `npm run test:unit:backend` passes
- `grep -n "action: str" apps/backend/modules/consent/domain/events.py` returns no matches
- `grep -n "action: Literal" apps/backend/modules/consent/domain/events.py` returns a match

## Handoff notes

- Line 86: `action: str` - change to `action: Literal["requested", "granted", "revoked", "declined"]`
- The `Literal` type needs to be imported from `typing` (already available in Python 3.11+)
- The values match the `status` CHECK constraint on `consent_consents` and `kind` CHECK constraint on `consent_events`
- Callers in `facade.py` already pass string literals - just verify they match the literal values
