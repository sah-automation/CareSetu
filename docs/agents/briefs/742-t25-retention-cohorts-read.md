# Brief - #742 Retention cohorts read

**Ticket:** #742 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Answer "does adoption stick?" - seven- and thirty-day retention cohorts, read from the daily product rollup so a thirty-day question never scans the raw event ledger.

- [ ] Seven-day and thirty-day retention cohorts are returned, read from the daily rollup rather than the raw ledger.
- [ ] A thirty-day query never scans the raw event ledger.
- [ ] Cohorts survive vendor retention limits, because the system of record holds them.
- [ ] Cohort figures are derived at read time from stored daily aggregates, so there is one source of truth.
- [ ] The read sits behind the same flat operator requirement as the existing nine reads.

## Read-list (in order)

1. Spec #717 - Implementation Decision 22; the retention user stories. (~0.7K)
2. The product daily rollup from #739 - its date grain, its actor keys, and which fields a cohort join needs. (~0.7K)
3. The product event ledger's relationship to the rollup, so you can prove the query does not touch the ledger. (~0.4K)
4. One existing operator read end to end - route, facade, query, domain dataclasses, wire decimals - as the shape to copy. (~1.6K)
5. The read-route round-trip integration test - extend it with a cohort that spans thirty days, so the no-ledger-scan criterion is actually exercised. (~1.2K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The funnel and active-user reads - #740, #741.
- The intake and care modules, the vendor exporters, the langfuse batch pull.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- This is the smallest ticket in the product wave by design. Resist adding a retention chart, a segment breakdown or a cohort comparison - those are not its criteria and they are what would push it over budget.
- The no-ledger-scan criterion is testable: seed thirty days in the rollup with the ledger empty (or truncated) and assert the cohorts still answer. That test is the deliverable.
- Cohort membership is a pseudonymised actor key, as everywhere else in this schema. Never a name, a phone number, or anything clinical.
- Derived at read time, not stored. A stored cohort table is a second source of truth that will disagree with the rollup after any recompute.
