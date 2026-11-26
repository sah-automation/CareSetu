# Brief - #724 Care-attribution edge table fed by the care-attributed event

**Ticket:** #724 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Record the patient-to-doctor edge that the care-attributed event carries, so the nightly rollup can attribute an intake's spend to a doctor without any module ever reading another module's tables. The edge table already exists; this ticket feeds it.

- [ ] The observability consumer records one edge row per care-attributed event, carrying the intake reference, the pseudonymous patient key and the pseudonymous doctor key.
- [ ] The edge row is written in the same transaction as the consumed-event ledger entry, so replaying the same event identifiers changes nothing.
- [ ] A single intake's spend resolves to exactly one doctor through the recorded edge.
- [ ] No participant resolves the pairing by reading the care schema; the edge exists only because the event said so.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 3 and 6. (~0.6K)
2. The observability consumer's handler-registration pattern - how an event type is declared, mirrored and routed to a handler. (~1K)
3. The registry-generated business-counter registration path in the consumer, as the closest precedent for a new event type with one effect. (~0.8K)
4. `run_handler` in the shared handler harness - the exactly-once contract, and what it hands the handler. (~0.7K)
5. The care-attribution edge table created by #723 - its columns, its uniqueness constraint and what the rollup expects to find. (~0.5K)
6. The pseudonymous-key helper #723 introduced. Reuse it exactly; do not introduce a second hashing convention. (~0.4K)
7. The consumer round-trip integration test - extend it for the edge write and its replay proof. (~0.9K)
8. The care-attributed event payload as actually published by #720 - read it from the registry or the producer, do not assume. (~0.4K)

## Do NOT read

- The care and partner modules beyond that event payload.
- The rollup domain - #725 consumes the edge; you do not derive anything from it here.
- The nine existing read queries, frontend sources, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- No migration in this ticket. The edge table was created by #723; if it does not exist, #723 has not landed.
- The edge may arrive _after_ the AI job rows that reference the same intake. That is expected, not an error - the rollup is what reconciles them, in #725. Do not try to make this write order-dependent.
- "Exactly one doctor" must be enforced by the schema, not only by the producer: a re-pick would otherwise write two edges and make attribution ambiguous. Decide the conflict rule and state it in the payload docstring.
- Reuse #723's pseudonymous-key helper verbatim. Two hashing conventions in one schema is how attribution silently stops reconciling.
