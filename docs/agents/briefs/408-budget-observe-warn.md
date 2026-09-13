# Brief - 408 T11 AI budget observe-and-warn (no hard stop)

**Ticket:** #408 · **Parent:** #397 · **Refreshed:** 2026-09-13
**Reading surface:** ~8K tokens (budget 10K) - within budget, largest read of the pass

## Scope

The AI budget is observe-and-warn only: spend is reported against the configured budget but never blocks an AI call. The gate consulted before egress becomes advisory - the pipeline reads the meter and proceeds regardless; an exhausted budget is logged/reportable only. `ai_monthly_budget_paise` stays as a Settings knob so a cap can be reintroduced later without a rewrite. The meter's authoritative Postgres-first SQL read path is untouched (Phase 14 consumes it). The deviation from spec #344's hard-stop wording and NFR-001 is recorded in the roadmap's decision-note area and the budget-meter docstring, and hard-stop wording is reconciled in the AI engineering standard's cost-aware-routing clause, ADR-0013's hard-stop sentence, the system-context EXT-002 constraints, the roadmap Phase 7 infrastructure item, and the worker/outbox runbook's degradation list. Acceptances: `allows_ai_call` is advisory (exhausted meter warns/logs, never blocks; budget-meter tests updated); the Settings knob and SQL read path unchanged; hard-stop wording reconciled across the listed docs + docstring.

## Read-list (in order)

1. `modules/intake/budget_meter.py` - `BudgetMeter`, `BudgetMeterResult.allows_ai_call` (:58-66), `read_spend_paise` SQL aggregate (:84-92, the authoritative Postgres-first path to keep); `meter`/gate (:100-122); docstring gains the deviation note (~1.8K)
2. `modules/intake/adapters/pipeline.py` - `_build_egress_gate` (:102-120) and the gate consultation at pipeline entry (:201-208) - becomes advisory (~1.2K)
3. `app/config.py` - `ai_monthly_budget_paise` (:231) + env wiring + validation - the knob stays (~0.6K)
4. The existing budget-meter tests + consumer-harness degrade test (`test_intake_pipeline_degradation.py` asserts the current hard-stop) - update to observe-and-warn (~1.5K)
5. Doc reconciliation targets (grep "hard stop"/"budget exhausted"): `docs/standards/ai-engineering-standards.md` (cost-aware-routing clause), `docs/adr/0013-*.md` (hard-stop sentence), `docs/architecture/system-context.md` (EXT-002 constraints), `docs/roadmap/implementation-roadmap.md` (decision-note area + Phase 7 infrastructure item), the worker/outbox runbook (degradation list) (~3K total, skim each to its clause)

## Do NOT read

- Provider adapters, `pipeline.py` write/finalize internals (those are #398/#399/#401's), frontend sources, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1732 passed (verified 2026-09-13)
- `npm run typecheck:backend` - mypy strict clean
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - consumer harness: meter-exhausted pipeline completes and warns; hard-stop tests updated
- `npm run lint`, `npm run scan` - docs/standards consistent

## Handoff notes

- Blocked by #399 (real cost makes the meter meaningful); the SQL read path and Settings knob remain untouched - no migration, no wiring (Phase 14 owns dashboard/alert)
- This is a DELIBERATE recorded deviation from spec #344 (`NFR-001`) - the deviation must be stated in the roadmap decision-note area and the docstring, not silently changed
- `docs/archive/` is superseded; do not reconcile anything there - only the live docs listed
