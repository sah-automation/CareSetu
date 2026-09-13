# Brief - T06 Budget meter + NFR-001 hard stop

**Ticket:** #350 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

AI spend becomes metered and capped: the authoritative monthly spend is the SQL aggregate over the `ai_jobs` table, compared against the configured NFR-001 freemium budget. The meter reports spend/remaining, and when the budget is exhausted it answers hard-stop so no new AI calls are made - subsequent intakes degrade to raw doctor review. The hard stop is enforced and tested as a gate, not a recommendation.

Acceptance criteria:

- [ ] Monthly spend is computed from the ai_jobs SQL aggregate (Postgres-first) for the current month
- [ ] Meter returns spend + remaining against the configured budget; exhausted budget yields the hard-stop result
- [ ] Hard-gate unit test: over-budget blocks the AI call decision
- [ ] Unit test: spend below budget allows the call; aggregate reflects rows inserted through the fake engine

## Read-list (in order)

1. Issue #344 Implementation Decisions (budget meter semantics) - the ratified meter contract (~1K)
2. `docs/prd/project-prd.md` NFR-001 section - budget definition and freemium cap (~1K)
3. `docs/standards/ai-engineering-standards.md` (cost metering) - metering/observability rules (~1.5K)
4. A module facade that already does a SQL aggregate for a read (e.g. partner directory or consent facade) - aggregate-read pattern (~1.5K)
5. `docs/architecture/internal-modules.md` §3.5 + `apps/backend/modules/intake/schema/models.py` - the ai_jobs table this aggregates over (T01 lands first) (~1.5K)

## Do NOT read

- `docs/archive`
- frontend sources
- AI gateway internals
- consumer/worker internals

## Baseline verify (must pass before the first edit)

- `npm run migration-check` - green at single head (verified 2026-09-08)
- `npm run test:unit:backend` - 1343 passed (verified 2026-09-08)
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`

## Handoff notes

- Spend is surfaced via a SQL aggregate (Postgres-first), not an in-memory counter; fake engine rows must reflect in the aggregate for the under-budget test.
- Hard-stop is a gate: over-budget blocks the call decision (intake degrades to raw doctor review, per T11).
