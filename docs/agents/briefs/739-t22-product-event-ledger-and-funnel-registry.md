# Brief - #739 Product event ledger, funnel-step registry and daily rollup

**Ticket:** #739 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Give the system a product event ledger in the observability schema and a daily rollup over it, so product KPIs live in the system of record rather than in a vendor whose fourteen-day retention makes monthly numbers structurally impossible. Funnel steps become a registry entry, not a schema change.

- [ ] A product event ledger in the observability schema carries timestamp, pseudonymous actor key, session key, trace identifier, funnel name, step, outcome and duration.
- [ ] Funnel steps are a registry matching the existing metric registry pattern: adding a step is a registry entry, not a schema change, and each step declares its allowed outcomes from a closed vocabulary of completed, abandoned and errored.
- [ ] A daily product rollup is what long windows and cohorts read, so a thirty-day query never scans the raw ledger.
- [ ] Every product event carries the trace identifier, so any funnel number can be traced back to the real user journey.
- [ ] Ledger writes are idempotent per event identifier; replaying the same identifiers changes nothing.
- [ ] The composer's entry step, published when a patient opens the composer, lands in the ledger, so an abandoned draft is distinguishable from a submit.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 22, 23, 24, 25, 26, 41; the product-analytics user stories. (~1.4K)
2. `docs/architecture/internal-modules.md` §4.2 - every event the funnel spans: the intake events, the pre-summary events, the care consult/prescription events, plus the new composer entry step from #721. You consume; you do not invent. (~1K)
3. The existing metric registry pattern in the rollup domain and its duplicate-key guard - the pattern to mirror for the funnel-step registry. (~0.7K)
4. The observability consumer's payload-mirror and handler-registration patterns, including the registry-generated registration path for an event type with one effect. (~1.2K)
5. `run_handler` in the shared handler harness - the exactly-once contract every ledger write must go through. (~0.7K)
6. The product event ledger and daily rollup tables created by #726 - their columns, and what the rollup shape expects to be able to answer. (~0.6K)
7. The pseudonymous-key helper from #723, reused exactly. (~0.3K)
8. The consumer round-trip integration test - extend it for the ledger write, the idempotency proof and the entry-step landing. (~1.1K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The funnel, active-user and retention reads - #740, #741, #742 build on this.
- The intake and care module internals beyond the event payloads you consume.
- The langfuse batch pull and the collector configuration.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- **Registry, not schema.** The criterion that distinguishes this ticket is that adding a funnel step touches no table. Write a test that adds a step to the registry and asserts the ledger and rollup handle it without a migration.
- The outcome vocabulary is closed: completed, abandoned, errored. A degraded fallback is _errored_, not abandoned (#740's read applies that, but the registry is where the rule lives). A re-record is its own outcome rather than a failure of the original.
- Active actors are derived from this ledger, never from a login event. There is no authentication event in the registry and adding one is explicitly out of scope.
- The trace identifier is on every row: it is the join key across the platform, the tracing backend and the AI backend.
- The daily rollup is what long windows read. If a thirty-day query can be satisfied by scanning the ledger, the rollup is not doing its job - that is #742's acceptance criterion, and it fails if the rollup shape here cannot support it.
