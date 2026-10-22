# Brief - #725 Daily per-actor attribution aggregate with nullable revenue and tier

**Ticket:** #725 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Derive a daily per-actor aggregate from the per-job spend rows, recomputed rather than accumulated, so late-arriving doctor attribution fills itself in without double-counting. Land the nullable revenue and tier dimensions on the same aggregate so turning monetization on is a data write, not a migration.

- [ ] The rollup upserts each (date, actor kind, actor key, provider, model, task type) row in full - recomputed from source, never incremented.
- [ ] When a care-attribution edge lands after its AI job, the next rollup fills the doctor key in with no double-counting.
- [ ] Running the rollup twice over the same data leaves byte-identical rows.
- [ ] The aggregate carries a nullable revenue column and a nullable tier key; both are empty today.
- [ ] Per-unit figures (cost per thousand input and output tokens, per request, per completed task, per patient, per doctor, cost-of-pass) are not stored here - they stay derived at read time, so there is one source of truth.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 6, 8, 9; Testing Decisions (the rollup round trip's idempotency expectations). (~1.2K)
2. The rollup domain's split: pure computation in the domain module, persistence in the adapter, and the generic upsert helper both use. Conforms to the pattern; do not add a second style. (~1.5K)
3. The daily per-actor aggregate table created by #723 - every column, its uniqueness constraint, and what "recompute in full" means for that constraint. (~0.8K)
4. The per-job spend table and the care-attribution edge table - the two inputs to the join. (~0.7K)
5. The rollup date-planning and run-ledger logic - where a rerun for a date is decided to be a no-op, and where an idempotent recompute must still be allowed. (~0.8K)
6. `weighted_percentile` and the average helpers in the same domain - reuse, do not reimplement. (~0.5K)
7. The rollup round-trip integration test - extend it for the recompute, the late-doctor fill and the run-twice-identical proof. (~1.2K)

## Do NOT read

- The nine existing read queries and the business read facet work - #731, #732, #733 build on this.
- Frontend sources, `docs/archive/`.
- The intake and care modules.
- The vendor exporters and the nightly workflow YAML beyond knowing the schedule exists.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run migration-check`

## Done-verify (acceptance criteria → commands)

- `npm run test:integration`
- `npm run test:unit:backend`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- **Recompute, never increment.** The whole reason for recomputation is the late-arriving doctor edge: the edge lands after the job row, so an incrementing rollup can never fill the doctor key in without double-counting. If your implementation increments anything, it is wrong.
- The run ledger is the existing idempotency key for "this date has been rolled". A recompute-in-full must still be reachable - decide how a rerun-for-a-date is expressed and keep it consistent with the existing backfill path.
- The per-unit metrics criterion is a _negative_ requirement: they must not appear as columns. This is the ticket where that is easiest to violate by reflex.
- Downstream: #731 and #732 read this table, #733 computes the cost outlier from it, #738 shows it. Column names decided here are a contract for all four.
