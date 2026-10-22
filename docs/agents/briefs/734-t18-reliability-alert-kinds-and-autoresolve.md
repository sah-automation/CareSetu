# Brief - #734 Reliability alert kinds with the auto-resolve policy

**Ticket:** #734 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Name every actionable condition. Add the new alert kinds - cost outlier, high error rate, high queue age, rate-limited provider, high backlog and latency objective breach - to the existing vocabulary, and make the auto-resolve behaviour explicit: budget, breaker, backlog and dead-letter alerts resolve when the condition clears, while a provider health drop deliberately never does.

- [ ] Cost outlier, high error rate, high queue age, rate-limited provider, high backlog and latency objective breach join the existing alert kinds.
- [ ] Budget, breaker, backlog and dead-letter alerts auto-resolve when the condition clears, so the operator's open list stays honest.
- [ ] A provider health drop never auto-resolves, so a degraded provider cannot quietly disappear from the board.
- [ ] Every new kind uses the existing dedupe marker, so a nightly rollup cannot raise the same alert twice.
- [ ] The latency objective breach alert measures a user-facing symptom, not an internal cause.

## Read-list (in order)

1. Spec #717 - Implementation Decision 20 and 42; the alert user stories; the sequencing note that SLO formalisation lands with the design records (#754). (~1K)
2. The rollup domain's alert kind vocabulary, the resolvable-kind set, the builders, the evaluators and the dedupe marker. (~1.5K)
3. The cost-outlier alert #733 added - copy its integration into this vocabulary rather than duplicating it. (~0.5K)
4. The provider health computation and its derived status - the input for the rate-limited-provider kind, and the reason a health drop must not auto-resolve. (~0.8K)
5. The queue depth and oldest-age derivation from #729 - the input for the high queue-age kind. (~0.6K)
6. The per-minute HTTP counter and the throughput/error-rate read from #727 - the input for the high error-rate kind. (~0.6K)
7. The non-functional requirements the latency objectives derive from, to align the latency breach threshold with a documented objective rather than a round number. (~0.6K)
8. The rollup round-trip integration test - extend it for each new kind and for the auto-resolve behaviour. (~1.2K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The alert acknowledgement endpoint - #735 owns the write path.
- The intake and care modules, the vendor exporters, the Grafana assets.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- Six new kinds is a lot of surface for one ticket. They share one mechanism; if the read-list has grown past budget, split the ticket rather than implementing all six shallowly.
- The provider-health exception is deliberate and must be expressed as data in the resolvable-kind set, not as a conditional buried in a builder. Someone will read the set to decide auto-resolve behaviour.
- "User-facing symptom" for the latency breach means the observable request latency against the documented objective. Do not alert on an internal function's duration - that pages on something no user experiences.
- #754 formalises the SLOs these alerts measure against. If the objective you alert on is not yet documented, note the threshold's derivation in the code and keep it consistent with what #754 writes.
- Dead-letter and backlog alerts already exist in some form; read before adding - "new kind" may mean "new threshold on an existing kind" for some of these six.
