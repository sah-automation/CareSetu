# Brief - #732 Business read: unit metrics, attribution and the not-captured margin reason

**Ticket:** #732 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Answer "what does one unit of value cost?" - cost per request, per completed task, per patient and per doctor, and cost-of-pass as spend divided by successful outcomes. Show who the heavy actors are: top patients by spend with the median, ninety-fifth percentile and maximum so one outlier cannot mislead the average, top doctors by spend, and the doctor each patient's cost was attributed to, so the two reconcile. Revenue and tier dimensions exist but stay empty, so margin returns null with an explicit not-captured reason rather than a misleading zero.

- [ ] Cost per AI request, per completed task, per patient and per doctor, and cost-of-pass, are all derived at read time - none is stored.
- [ ] Cost-of-pass divides spend by successful outcomes, so value delivered is the denominator rather than a raw token rate.
- [ ] Top patients by spend for the period are returned with the median, ninety-fifth percentile and maximum, so one outlier cannot be read as the average.
- [ ] Top doctors by spend for the period are returned, and per-patient and per-doctor figures reconcile through the recorded attribution edge.
- [ ] The revenue and tier dimensions are read and returned; with no revenue captured, every margin percentage returns null carrying an explicit not-captured reason, never a zero.
- [ ] A single headline AI cost-of-goods figure for the month is available for the month.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 8, 9; the unit-economics user stories; Out of Scope (no monetization model, revenue capture explicitly out). (~1.2K)
2. The same operator read seam #731 uses - route, facade, query, domain dataclasses, wire-decimal quantisation. Conform to it exactly. (~1.5K)
3. The daily per-actor aggregate from #725 and the care-attribution edge table - the two inputs, and the columns that make reconciliation possible. (~0.8K)
4. How the existing reads express a value that cannot be computed: look for an existing null-with-reason shape before inventing one. If none exists, this ticket establishes it and it must be machine-readable, not prose in a string field only. (~0.6K)
5. `percentile` and `weighted_percentile` in the rollup domain - reuse for the median/p95/max figures rather than writing new statistics. (~0.5K)
6. The read-route round-trip integration test - extend it for these facets, including a null-margin assertion that distinguishes null from zero. (~1.2K)

## Do NOT read

- The frontend client and panel page - #737 owns the page.
- The outlier alert - #733.
- The spend/period/burn/breakdown facets - #731 owns those; this ticket adds to the same read, it does not re-derive them.
- `docs/archive/`, the intake and care modules, the vendor exporters.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- **Null, not zero, for margin.** A zero margin percentage is indistinguishable from a real zero-revenue month, and a finance lead will quote it. The not-captured reason is the deliverable; the null is the mechanism.
- "Cost-of-pass" is spend divided by successful outcomes, not by tokens and not by raw requests. The denominator is the completed-outcome count from the aggregate.
- Reconciliation criterion: per-patient totals and per-doctor totals must agree through the attribution edge. Write a test that asserts they do - that test is the real deliverable of the attribution model.
- Top-N lists are people-shaped data in a PHI-free schema: keys stay pseudonymous. No names, no contact details, no clinical context in a top-patient list.
- Derived at read time means it is recomputed per request. Do not cache it into the aggregate; that is the two-sources-of-truth trap the spec calls out.
