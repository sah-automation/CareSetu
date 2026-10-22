# Brief - #728 Degraded provider board with the last error written

**Ticket:** #728 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Give a support engineer a per-provider board that names each upstream model API and whether it is healthy, degraded or down, so a CareSetu bug is distinguishable from an upstream outage. The provider health row already carries a last-error column that nothing ever writes; start writing it, and derive the status rather than storing it.

- [ ] The provider health row's last-error column is written by the rollup, so a degraded provider can be named rather than inferred.
- [ ] Each provider resolves to healthy, degraded or down from its rate-limit count, timeout count, success rate and circuit-breaker state.
- [ ] The board shows rate-limit rejections, timeouts, success rate and the fiftieth, ninety-fifth and ninety-ninth percentile latency per provider.
- [ ] Circuit-breaker state is shown per provider.
- [ ] The board is served from the observability module's own tables; no cross-module read is introduced.
- [ ] A provider health drop never auto-resolves, so a degraded provider cannot quietly disappear.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 18 and 20; the provider-board user stories. (~0.9K)
2. The rollup's provider-health computation and its upsert - where the windowed counters, success rate and percentiles are already computed, and the exact place the last-error column is omitted. (~1.3K)
3. The provider health table, including the breaker state column's vocabulary and the last-error column's type. (~0.6K)
4. The existing health read end to end - route, facade, query, domain dataclasses, wire decimals - and what it already exposes about providers. Extend it; do not build a parallel read if the surface fits. (~1.5K)
5. How a failure carries an error message to the rollup: the failed AI job event's reason field, and what is available at the point the health row is written. (~0.7K)
6. The alert auto-resolve kind set, so the "never auto-resolves" rule is expressed as data rather than a special case. (#734 covers the reliability kinds; the exception may already be visible in the existing set.) (~0.5K)
7. The rollup and read-route round-trip integration tests - extend both. (~1.1K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The circuit breaker and the AI gateway implementations - the breaker **state** is already recorded in observability; you read it, you do not change it.
- The langfuse batch pull and the collector configuration.
- The intake and care modules.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- **Derived, not stored.** Healthy/degraded/down is computed at read time from the counters. Storing a status column would add a second source of truth that the rollup's recompute could contradict.
- The last-error text must be PHI-free and bounded in length. Provider error bodies can echo request content - sanitise before it lands in the observability schema, and cap it.
- A "down" provider usually has no successful samples in the window, which makes success rate null or zero. Write that case explicitly; it is the one an operator most needs to be right about.
- The never-auto-resolve rule belongs in the resolvable-kind set as an omission that is asserted by a test, so nobody "tidies it up" later.
- #734 adds the rate-limited-provider alert kind on top of this board's inputs; #738 renders it.
