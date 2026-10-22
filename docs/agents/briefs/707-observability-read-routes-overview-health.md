# Brief - 707 C1b - Overview / health / alerts / deeplinks routes

**Ticket:** #707 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~8.8K tokens (budget 10K) - within budget

## Scope

Add the remaining five operator read routes: `GET /v1/operator/observability/overview` (headline KPIs), `/latency` (p50/p95/p99 by provider and route), `/health` (dependency and outbox health - database, cache, dispatcher backlog, dead-letter rows, circuit-breaker state), `/alerts` (alert feed), and `/deeplinks` (Grafana/Sentry/Langfuse URLs). Same operator-only guard and error envelope.

### Acceptance criteria

- [ ] All five routes registered, operator-only, with the shared envelope for refused callers.
- [ ] `overview` returns the documented headline KPIs; `health` reports dependency + outbox state; `alerts` returns the feed; `deeplinks` returns configured vendor URLs.
- [ ] Routes with no configured vendor return an empty/absent link rather than erroring.
- [ ] A route unit test covers principal handling and response shape; the integration test asserts each response against seeded data.
- [ ] `npm run typecheck`; `npm run test:unit:backend` pass.

Blocked by #692 child B4b (business/alerts) and B5a (health/percentiles).

## Read-list (in order)

1. The C1a observability read facade + router (`cost`, `/cost/trend`, `usage`, `quality`) - extend the same router and facade; match its view models, `app.state` binding, and registration. (~1.5K)
2. `bus/dispatcher.py` `discover_outbox_tables` (+ the outbox row contract) and `bus/outbox_ddl.py` status constants / `outbox_table` - the sanctioned outbox-only read for the `health` route's backlog + dead-letter counts. (~1.8K)
3. `app/gateway/rbac.py` `require_operator` and `app/gateway/errors.py` `ErrorEnvelope` / `register_gateway_error_handlers` - the same operator guard and 401/403 envelope. (~0.8K)
4. B3 schema models `obs_alert_events` (feed), `obs_ai_provider_health` (latency + health), `obs_business_daily` (overview KPIs) - the documented shapes. (~1.7K)
5. A5 observability Settings gates + vendor deeplink env vars (`SENTRY_DSN`, `LANGFUSE_PUBLIC_KEY`/`LANGFUSE_HOST`, Grafana/OTel endpoint) in `app/config.py` + `.env.example` - the `deeplinks` source; missing config -> empty/absent link, never an error. (~1.2K)
6. `docs/plans/plan-phase14-observability.md` §9.1 (route table) + §11 (health/alert definitions) - the route contract. (~1K)
7. `tests/unit/test_access_history_route.py` - route unit-test prior art (stub facade on `app.state`, mint tokens, assert 200/401/403). (~0.8K)

## Do NOT read

- Anything outside the read-list (frontend, consumer/rollup internals, other modules' schemas).

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS (measured 2026-10-12).
- `npm run test:unit:backend` - PASS (2925 passed, measured 2026-10-12).

## Done-verify (acceptance criteria → commands)

- `npm run typecheck` - PASS.
- `npm run test:unit:backend` - PASS, including a route unit test covering principal handling (anonymous 401 / non-operator 403) and each route's response shape, plus a "no vendor configured -> empty/absent link" case.
- `npm run test:integration` - if a local native Postgres is reachable (skips otherwise): seed the observability tables and assert each of the five responses against the seeded data.

## Handoff notes

- Extend, do not duplicate: add the five routes to the C1a observability router and the five read methods to its read facade, keeping them thin adapters (parse -> facade -> typed view, api-standards §1). All reads stay in MOD-013's `observability` schema.
- `health` is the one route with a sanctioned outbox read: reuse `discover_outbox_tables` + the outbox status constants for backlog/dead-letter (the dispatcher/migration harness are the only legal cross-schema readers, ADR-0003) - never read another module's domain tables. Database/cache/breaker state resolve through the read facade / Settings, not raw cross-schema SQL.
- `deeplinks` is env-gated (plan §4 gates): read the vendor URLs from the A5 Settings; when a vendor is unconfigured, return an empty/absent link. The route must never fail because a vendor is absent (mirror the Redis/Langfuse no-op pattern).
- Reuse the gateway guard + envelope exactly (`require_operator`, `error_response`); do not add a module-level RBAC error handler.
- Keep the alert feed PHI-free (`obs_alert_events.payload`), matching `error-handling-observability.md` §5.
