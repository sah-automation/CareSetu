# Brief - #752 Annotation queue fed by doctor review outcomes

**Ticket:** #752 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Turn human judgement into data: an annotation queue fed by doctor review outcomes, which is the human signal the technical evaluators are calibrated against. One queue ships; the richer dataset workflow stays deferred.

- [ ] An annotation queue is fed by doctor review outcomes, so human judgement becomes training and evaluation data.
- [ ] Queue entries are PHI-free, consistent with the rest of the observability schema.
- [ ] The queue carries the same trace identifier the platform, the tracing backend and the AI backend share, so one identifier joins every tool.
- [ ] No LLM-as-a-judge and no judge-to-human agreement measurement ship here - both remain deferred.
- [ ] Review outcomes reach the queue through events, never by reading another module's tables.

## Read-list (in order)

1. Spec #717 - Implementation Decision 40; Out of Scope (the richer dataset workflow). (~0.9K)
2. The doctor review outcome events and their payloads - what a review actually carries today, and what it does not. (~0.9K)
3. The existing consumer pattern that turns an event into an observability row, plus the consumed-event ledger's exactly-once contract. (~0.9K)
4. The score shape #751 established, so human annotations and technical scores can be compared in one place. (~0.5K)
5. The observability schema's PHI-free rule and the pseudonymous-key helper from #723. (~0.5K)
6. The trace identifier propagation contract: the accessor, the outbox column and the ledger column. (~0.4K)
7. The consumer round-trip integration test - extend it for the queue write and its replay proof. (~0.8K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The doctor console internals, the doctor profile and case surfaces.
- The Grafana assets, the collector configuration, the business and reliability reads.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- Events only. A queue fed by reading the care schema's review rows would be the cross-module read this whole programme is designed to avoid; if the review outcome is not on the bus, that gap is a separate ticket, not a licence to read across.
- PHI-free is a hard constraint, and review outcomes are exactly where clinical content would leak in. Take the outcome _classification_ and the trace identifier, not the doctor's free-text rationale.
- One queue ships. Resist adding assignment, review UI, dataset versioning or agreement measurement - all explicitly deferred.
- The trace identifier is what makes an annotation joinable to a technical score later. Do not substitute a synthetic identifier for it.
