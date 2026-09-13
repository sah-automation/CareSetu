# Brief - T12 Patient intake HTTP routes

**Ticket:** #356 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

A patient can drive the whole intake over HTTP: submit an intake, upload media, re-record, get an intake + pre-summary, and save patient pre-summary edits, all under patient RBAC with request validation (mode/language enums, character and seconds/attempt caps) and the standard error envelope. Routes read the facade from app state and contain no business logic - route-boundary tests use a stubbed facade.

Acceptance criteria:

- [ ] Each endpoint returns the contract shape in route-boundary tests with a stubbed facade (prior art: partner route tests)
- [ ] Unauthenticated requests are rejected; partner/doctor-scope callers cannot hit patient routes
- [ ] Invalid mode/language and over-cap submissions yield the standard error envelope (42x)
- [ ] No business logic in route handlers - they delegate to the facade

## Read-list (in order)

1. `apps/backend/modules/partner/adapters/routes.py` - route conventions (~2K)
2. `apps/backend/app/gateway/rbac.py` + `principal.py` - scope dependencies (require_patient; partner/doctor rejection) (~1.5K)
3. The error-envelope and response-model conventions used by partner routes and their tests - `tests/unit/test_partner_register_route.py` for the stubbed-facade route-boundary pattern (~2K)
4. Facade methods + DTOs from T07/T08/T09 - submit/upload/re-record/get/save-edits shapes (~2K)

## Do NOT read

- `docs/archive`
- frontend sources
- AI gateway internals
- worker internals

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1343 passed (verified 2026-09-08)
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`

## Handoff notes

- Doctor identity today is a partner_type value (`partner_type: Literal["doctor", ...]`), not a separate RBAC scope; patient routes reject partner/doctor-scope callers via `require_patient` guard, consistent with `apps/backend/app/gateway/rbac.py`.
- Route-boundary tests stub the facade via `app.state.intake_facade = Stub...` on the TestClient - mirror `tests/unit/test_partner_register_route.py` (lines ~57-76).
- Routes are thin: read facade from app state, delegate, no business logic.
