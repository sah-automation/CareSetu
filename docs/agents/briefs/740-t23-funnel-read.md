# Brief - #740 Funnel read

**Ticket:** #740 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Answer "is the product working?" - a funnel from the moment a patient opens the composer, so a workflow that silently dies at transcription and one that runs to a completed prescription stop looking identical. Each step's completion and abandonment, the thinking time between steps, and the outcome that ended it are all reported together.

- [ ] The funnel runs from composer opened through intake captured, pre-summary ready, consult complete, prescription drafted, and prescription approved or case closed.
- [ ] Each step is counted, completed and abandoned, so step-to-step conversion is computable.
- [ ] The median gap between one step and the next is returned, so thinking time is visible and not only machine time.
- [ ] Task success rate and abandonment rate are returned together in one view, so the two are never quoted apart.
- [ ] A step that ends because of a degraded fallback scores as an errored outcome, so a broken path is never read as a quiet drop-off.
- [ ] A re-record is its own outcome, so a corrected attempt is not scored as a failure of the original.
- [ ] The funnel is filterable by outcome, so the abandoned path can be isolated.
- [ ] Workflows ending in an issued e-prescription are distinguishable from those ending with the case closed without one.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 23, 24, 25; the funnel user stories. (~1.1K)
2. The funnel-step registry and its outcome vocabulary from #739 - the step names, their declared allowed outcomes, and the degraded-fallback and re-record outcome rules. (~0.8K)
3. The product event ledger and daily rollup - the columns this read aggregates, and the session key that makes a gap between two steps computable. (~0.7K)
4. One existing operator read end to end - route, facade, query, domain dataclasses, wire decimals - as the shape to copy. (~1.8K)
5. The existing percentile helpers in the rollup domain, for the median step gap. (~0.5K)
6. The read-route round-trip integration test - extend it: per-step counts, the errored-fallback case, the re-record case, the outcome filter and the two legitimate terminal outcomes. (~1.3K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The active-user and retention reads - #741, #742.
- The intake and care module internals beyond the event payloads.
- The reliability read internals.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- Success rate and abandonment rate in **one** response, never two figures a caller can quote apart. If a client could render one without the other, the shape is wrong.
- Step-to-step conversion needs an explicit denominator convention when a step can be reached without passing the previous one. State the convention in the response or in the query's docstring - silently picking one is how a funnel starts lying.
- Both terminal outcomes are legitimate: an issued e-prescription and a case closed without one. Do not score the second as a failure. The criterion exists because an earlier shape conflated them.
- The degraded fallback and re-record outcome rules live in the registry (#739). Read them from there rather than re-deriving them here, so the read and the registry cannot drift.
- Every step carries a trace identifier in the ledger; surfacing it per step is what makes a funnel number defensible.
