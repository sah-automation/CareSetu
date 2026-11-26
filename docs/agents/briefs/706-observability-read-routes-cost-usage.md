# Brief - 706 C1a - Observability read facade + cost/usage/quality/latency routes

**Ticket:** #706 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~8.2K tokens (budget 10K) - within budget

## Scope

Expose MOD-013's read facade and the first four operator read routes: `GET /v1/operator/observability/cost`, `/cost/trend` (window default 30 days), `/usage`, and `/quality`. Routes are operator-only through the shared `require_operator` gateway dependency; wrong-role and anonymous callers are refused with the shared gateway error envelope, and query params are validated. Each returns the documented shape from the observability schema (Postgres as system of record).

### Acceptance criteria

- [ ] A read facade in the observability module serves the four documented aggregates; no cross-schema SQL.
- [ ] All four routes are registered and require the operator scope; anonymous -> 401, wrong role -> 403 via the shared envelope.
- [ ] `cost/trend` honours a validated `days` param with a 30-day default.
- [ ] A route unit test (fake facade) covers principal handling, param validation, and response shape; an integration test asserts each response against seeded data.
- [ ] `npm run typecheck`; `npm run test:unit:backend` pass.

Blocked by #692 child B4a (usage aggregates) and B5a (rollup/percentiles).

## Read-list (in order)

1. `modules/audit/adapters/routes.py` - the operator read-route prior art: thin adapter, `Annotated[Principal, Depends(require_operator)]`, typed `response_model`, validated `Query` params. (~1.2K)
2. `app/gateway/rbac.py` `require_operator` - the exact guard the four routes declare. (~0.3K)
3. `app/gateway/errors.py` `ErrorEnvelope` + `register_gateway_error_handlers` - the 401/403 envelope refused callers get (do not add a module error handler for RBAC). (~0.7K)
4. `app/main.py` - the `include_router(...)` block and the facade-on-`app.state` construction pattern (`audit_router`/`app.state.audit_facade`) to mirror for the observability router + read facade. (~2K)
5. B3 schema models `obs_ai_cost_budget`, `obs_ai_usage_daily`, `obs_ai_provider_health` - the documented shapes the cost / usage / quality routes serve. (~1.5K)
6. `docs/plans/plan-phase14-observability.md` §9.1 - the read-API table and the `days=30` default. (~0.5K)
7. `docs/standards/api-standards.md` §1-§4, §6 - thin adapters, error envelope, strict Pydantic validation, pagination, RBAC. (~1K)
8. `tests/unit/test_access_history_route.py` - route unit-test prior art: stub the facade on `app.state`, mint tokens, assert 200 / 401 / 403 / 422. (~1K)

## Do NOT read

- Anything outside the read-list (frontend, the remaining C1b routes, consumer/rollup internals, other modules' schemas).

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS (measured 2026-10-12).
- `npm run test:unit:backend` - PASS (2925 passed, measured 2026-10-12).

## Done-verify (acceptance criteria → commands)

- `npm run typecheck` - PASS.
- `npm run test:unit:backend` - PASS, including a route unit test with a fake facade covering principal handling, `days` param validation (default 30, invalid rejected), response shape, anonymous -> 401, wrong role -> 403.
- `npm run test:integration` - if a local native Postgres is reachable (skips otherwise): seed the observability tables and assert each route's response against the seeded data.

## Handoff notes

- Copy the audit route/facade pairing end to end: a typed read facade (see `modules/audit/facade.py` `AuditFacade.query_audit`) built once in `create_app` and stored as `app.state.<...>_facade`; routes read it via `cast(..., request.app.state.<...>_facade)`. Router tests stub that attribute wholesale.
- Routes are thin adapters only (api-standards §1): parse -> call facade -> return a Pydantic view. No business logic and no cross-schema SQL in the route or facade - all reads are against MOD-013's own `observability` schema (module isolation rule, ADR-0003).
- Owner rule: the operator scope is the only accepted role (`NFR-SEC-003`, api-standards §6); anonymous is refused 401, non-operator 403, both through `error_response` (no token/PHI echo).
- `cost/trend` must validate `days` with a bounded `Query` (default 30) and reject out-of-range/negative values at the edge (422 with the standard `details` list).
- Register the new router + facade in `app/main.py` next to the existing module wiring; no frontend or session/CORS changes (ADR-0007 hard gate does not apply to this backend-only read surface, but keep it so).
