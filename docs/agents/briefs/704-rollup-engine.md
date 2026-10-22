# Brief - 704 B5a - Rollup engine: percentiles + provider health + budget + alert eval

**Ticket:** #704 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~8.7K tokens (budget 10K) - within budget

## Scope

Build the rollup engine MOD-013 runs off the request path: a generic, registry-driven rollup (`metric_key` -> computation) that, given a date, recomputes percentile-based aggregates - p50/p95/p99 duration and success rate into `obs_ai_provider_health`, snapshots current spend into `obs_ai_cost_budget`, and evaluates alert thresholds (budget > 80%, provider health drop, outbox backlog, breaker open, dead-letter row) into `obs_alert_events`. Make the aggregation functions pure and database-free so they are unit-tested in isolation; expose an invocation seam (command/endpoint) the nightly job calls.

### Acceptance criteria

- [ ] A rollup registry lets later phases add a metric without schema churn.
- [ ] Percentile/health/budget/alert computations are pure functions, unit-tested without a database.
- [ ] Running the rollup for a date refreshes `obs_ai_provider_health`, snapshots `obs_ai_cost_budget`, and emits threshold alerts.
- [ ] `obs_business_daily` remains the generic store for rollup metrics.
- [ ] `npm run typecheck`; `npm run test:unit:backend` pass.

Blocked by #692 child B4a and B4b (consumer + aggregates feed the rollup).

## Read-list (in order)

1. B3 schema models `obs_ai_usage_daily`, `obs_ai_provider_health`, `obs_ai_cost_budget`, `obs_alert_events`, `obs_business_daily` - the columns/keys the rollup reads and writes. (~1.8K)
2. B4a/B4b consumer + facade - the accumulated usage/business store the rollup refreshes and the `metric_key` registry shape it extends. (~2K)
3. `bus/dispatcher.py` `discover_outbox_tables` / `process_outbox_table` / `retry_status_after_failure` plus `bus/outbox_ddl.py` status constants + `outbox_table` - the sanctioned outbox-only read for backlog/dead-letter alert inputs (never domain tables). (~2.2K)
4. `modules/intake/budget_meter.py` `BudgetMeter.read_spend_paise` / `BudgetMeterResult` - the authoritative spend read and the observe-and-warn paise semantics to preserve. (~1K)
5. `docs/plans/plan-phase14-observability.md` §8 (rollup) + §11 (SLOs & alerting minimum set) - the rollup contract and threshold set. (~1.3K)
6. `docs/standards/error-handling-observability.md` §5 - the minimum alert set and no-PHI alert rule. (~0.4K)

## Do NOT read

- Anything outside the read-list (frontend, the nightly workflow wiring B5b, unrelated modules, other schemas' domain tables).

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS (measured 2026-10-12).
- `npm run test:unit:backend` - PASS (2925 passed, measured 2026-10-12).

## Done-verify (acceptance criteria → commands)

- `npm run typecheck` - PASS.
- `npm run test:unit:backend` - PASS, including pure-function unit tests for percentiles (p50/p95/p99), success rate, budget snapshot, and each alert threshold, with no database.
- `npm run test:integration` - if a local native Postgres is reachable (skips otherwise): running the rollup for a date against seeded `obs_ai_usage_daily` refreshes `obs_ai_provider_health`, snapshots `obs_ai_cost_budget`, and emits the expected `obs_alert_events`.

## Handoff notes

- Keep the pure core in `domain/` (coding-standards §2): percentile/success/health/budget/alert evaluation are DB-free functions; the adapter layer only loads rows, calls the pure functions, and upserts.
- Rollup registry pattern: `metric_key -> computation` so a later phase adds a metric without schema churn; `obs_business_daily` is the generic store (plan §7.2, §8).
- Follow the budget meter's Postgres-first, paise, observe-and-warn semantics (`modules/intake/budget_meter.py`, PS-10 #408) - the rollup snapshots spend, never enforces it.
- Outbox backlog/dead-letter/breaker are the only cross-schema reads the rollup legitimately needs; reuse the dispatcher's `discover_outbox_tables` + outbox-table contract rather than writing new cross-schema SQL (module isolation rule, ADR-0003; the dispatcher/migration harness are the sanctioned readers).
- Expose the invocation seam as a small async `run_rollup(engine, target_date)` plus a thin runnable entrypoint (mirroring `worker.main`'s `python -m ...` convention) so B5b's GitHub Action can call it without the web process awake.
- Alert rows carry severity/kind/title and a PHI-free JSON payload only (`error-handling-observability.md` §5).
