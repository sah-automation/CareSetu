# Brief - FIX-5 Fix consent-log counterparty_type vocabulary

**Ticket:** #225 · **Parent:** #209 · **Refreshed:** 2026-08-25
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

`read_consented_history` accepts a spec-compliant `counterparty_type` (`doctor`/`lab`/`chemist`) instead of hardcoding `"partner"`. Frontend consent API type updated to match.

**Acceptance criteria:**

- `ConsentedReadRequest` in `health/adapters/routes.py` includes a `counterparty_type` field validated against `doctor | lab | chemist`
- Route passes the validated `counterparty_type` to the facade instead of hardcoding `"partner"`
- `apps/frontend/src/lib/consent/api.ts` `GrantConsentRequest.counterparty_type` already uses the correct enum - verify alignment
- Integration test proves consent-gated read works with each counterparty type
- `npm run test:unit:backend` passes

## Read-list (in order)

1. `apps/backend/modules/health/adapters/routes.py:88-128` - `ConsentedReadRequest` + route handler (~174 tokens)
2. `apps/backend/modules/consent/domain/events.py` - `CounterpartyType` vocabulary (~191 tokens)
3. `apps/backend/modules/consent/schema/models.py:61-63` - CHECK constraint on `counterparty_type` (~136 tokens)
4. `apps/frontend/src/lib/consent/api.ts:158-167` - `GrantConsentRequest` type to verify alignment (~199 tokens)

**Total:** ~700 tokens of reading, well within budget.

## Do NOT read

- Facade internals
- Frontend pages/components
- Standards docs

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - verify current state
- `grep -n "partner" apps/backend/modules/health/adapters/routes.py` - confirm hardcoded value

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` passes
- `grep -n "counterparty_type" apps/backend/modules/health/adapters/routes.py` shows the field in request model
- `grep -n '"partner"' apps/backend/modules/health/adapters/routes.py` returns no matches

## Handoff notes

- The route currently hardcodes `counterparty_type="partner"` at line 126
- The schema CHECK constraint only allows `doctor`, `lab`, `chemist` - `"partner"` would fail on a real write
- The `CounterpartyType` literal is defined in `consent/domain/events.py` - import it or duplicate the literal
- The frontend `GrantConsentRequest` already uses `"doctor" | "lab" | "chemist"` - no frontend change needed, just verify alignment
