# Brief - T13 Doctor review route (contract only)

**Ticket:** #357 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

A doctor can review-and-edit an intake pre-summary over HTTP as the backend contract for the Phase 8 case workspace: the mark_pre_summary_reviewed endpoint under doctor RBAC, taking the corrections payload with the standard error envelope and validation. No doctor UI ships in this phase - only the route and its route-boundary tests.

Acceptance criteria:

- [ ] The review route calls mark_pre_summary_reviewed with the review DTO and returns the reviewed result shape
- [ ] Doctor-scope callers are allowed; patient/partner and unauthenticated callers are rejected
- [ ] Malformed correction payloads yield the standard error envelope
- [ ] Route-boundary test with stubbed facade proves the HTTP contract

## Read-list (in order)

1. `apps/backend/modules/partner/adapters/routes.py` + a doctor-scoped route example - `apps/backend/modules/health/adapters/routes.py` (doctor represented via `require_partner` + `partner_type: "doctor"`) for the scope dependency (~2K)
2. The mark_pre_summary_reviewed signature/DTO from T09 - the review + corrections payload (~2K)
3. `apps/backend/app/gateway/rbac.py` - scope guards and InsufficientScopeError (~1.5K)
4. `tests/unit/test_partner_register_route.py` - stubbed-facade route-boundary test pattern (~1.5K)

## Do NOT read

- `docs/archive`
- frontend sources
- AI gateway internals
- pipeline internals

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1343 passed (verified 2026-09-08)
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`

## Handoff notes

- Doctor access today is `require_partner` + `partner_type == "doctor"` (health routes), since there is no separate doctor RBAC scope yet - follow that convention for the doctor-scope dependency.
- Route-boundary test stubs the facade on app state (pattern: `tests/unit/test_partner_register_route.py`). No doctor UI in this phase.
