# Brief - #726 Gateway error capture and the runtime capture table set

**Ticket:** #726 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Capture server errors where they happen but never on the failing request's hot path. The gateway error seam appends a structured, PHI-free record to a bounded in-process buffer; a worker drains that buffer into the observability error stream. This ticket also owns the second of the spec's two additive observability migrations, creating the whole runtime-capture and product table set that the follow-on tickets consume.

- [ ] One additive migration creates the error event table, the per-minute HTTP counter, the product event ledger and its daily rollup. No existing table's semantics change.
- [ ] The alembic single-head gate and the cross-schema foreign key scan both pass.
- [ ] The gateway error seam appends a structured PHI-free record - templated route, method, status class, trace id, fingerprint - to a bounded in-process buffer. Nothing is written on the failing request's hot path.
- [ ] A worker drains the buffer into the error stream through the module facade; the buffer is bounded, so a storm drops rather than growing without limit.
- [ ] Driving a real server-error response through the real ASGI application and then draining produces exactly one captured record, carrying the trace identifier.
- [ ] Records carry route templates, never concrete request paths, so cardinality stays bounded and no identifier leaks into telemetry.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 12, 13, 14, 41, 43; Testing Decisions (the gateway capture folds into the main round trip). (~1.3K)
2. `docs/adr/0024-*.md` - the observability topology decision: PHI-free telemetry by construction, free-tier posture, Postgres as system of record. (~0.5K)
3. The gateway error seam and the error envelope it emits; the trace context accessor it already stamps. (~1K)
4. The trace middleware: how the trace identifier is minted, validated and made available, and how the request-scoped route template can be reached from an exception handler. (~0.9K)
5. The observability module's facade write path - the only legal way this module writes to its own schema. (~0.8K)
6. A worker entry point and its schedule precedent - the nightly rollup worker and the workflow that runs it. (~0.9K)
7. The observability schema models and the current head migration: the additive raw-DDL convention and the table naming prefix. (~0.9K)
8. The consumed-event ledger helper and its exactly-once contract, to decide how a drained record is deduplicated. (~0.6K)
9. The consumer round-trip integration test and the read-route round-trip's full-vertical setup (real app, real dispatcher, minted operator token) - extend it to drive a real 5xx and drain. (~1.2K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The error feed read (#730), the counter read (#727), the product ledger consumer (#739) - you create their tables, you do not build their reads.
- The intake and care modules, the AI gateway implementations.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run migration-check`

## Done-verify (acceptance criteria → commands)

- `npm run test:integration`
- `npm run migration-check`
- `npm run test:unit:backend`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- **Four tables, one migration, one owner.** The per-minute counter, product ledger and product rollup are created here and consumed by #727, #739 and their followers. This mirrors #723 on the attribution side; the spec fixes these as the two migrations of Batch 3.
- The buffer must be bounded with an explicit drop policy. An unbounded buffer turns an error storm into an out-of-memory kill, which is worse than the outage it was recording.
- Route **templates**, never concrete paths. A concrete path puts an identifier into telemetry and makes cardinality unbounded - both are named criteria.
- The fingerprint (#730 collapses by it) is decided here. Derive it from the stable attributes of a failure only: a fingerprint that includes a trace id or a timestamp collapses nothing.
- In-process buffer and in-process counter are correct for the current single-instance topology and are the stated reason horizontal scaling stays deferred. Do not add a Redis hand-off; that is a different decision with its own ticket.
- Draining goes through the module facade, not direct table access.
