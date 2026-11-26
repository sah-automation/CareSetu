# Brief - #723 Attribution table set and per-job AI spend rows

**Ticket:** #723 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Give observability a granular, per-job record of AI spend so per-patient and per-doctor attribution becomes arithmetic rather than guesswork. This ticket owns the first of the spec's two additive observability migrations: it creates the whole attribution table set, and the two follow-on tickets consume the tables it creates.

- [ ] One additive migration creates the granular per-job spend table, the care-attribution edge table, and the daily per-actor attribution aggregate with its nullable revenue and tier columns. No existing table's semantics change.
- [ ] The alembic single-head gate and the cross-schema foreign key scan both pass.
- [ ] The AI job consumer writes one PHI-free row per AI job: usage date, intake reference, pseudonymous patient key, nullable pseudonymous doctor key, provider, model, task type, input and output tokens, cost in paise, status and trace id.
- [ ] Patient and doctor keys are one-way hashes of identity references; no raw identity reference and no clinical content lands in the observability schema.
- [ ] Replaying the same event identifiers leaves every row count unchanged.
- [ ] `draft` appears as a produced task type in the new rows, proving the metered drafting leg.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 5, 6, 7, 43; Testing Decisions (the primary round-trip seam). (~1.5K)
2. `docs/adr/0025-*.md` - the module schema registration decision: additive-only, no cross-schema FKs, PHI-free, idempotent via the consumed-event ledger. (~0.5K)
3. The observability consumer's AI job payload mirrors and the two explicit handlers - the insertion point for the per-job write. (~1K)
4. `run_handler` in the shared handler harness - the exactly-once contract: ledger row and effect in one transaction, replay is a no-op. Do not reimplement it. (~0.8K)
5. The observability schema models module - table naming prefix, metadata schema, existing aggregate shapes to imitate. (~1K)
6. The current head migration and the one that created the schema - the hand-written raw-DDL convention and the naming scheme. (~1K)
7. How observability aggregates already pseudonymise an identity, if they do. If no such helper exists, this ticket introduces one and it must be pure and unit-testable. (~0.5K)
8. The consumer round-trip integration test - the shape to extend for the per-job row and for the replay proof. (~1K)

## Do NOT read

- The nine existing read queries - #731 and #732 build on this table; you write no read here.
- The rollup domain's aggregate derivation - #725 owns the daily aggregate computation; you only create its table.
- Frontend sources, `docs/archive/`.
- The intake pipeline internals beyond the event payloads.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run migration-check`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:integration`
- `npm run migration-check`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- **This ticket creates three tables and uses one.** The care-attribution edge table (#724) and the daily per-actor aggregate (#725) are created here and filled by those tickets. That is deliberate: the spec fixes this as the first of two migrations.
- The migration must be additive and must not alter an existing table's semantics. The cross-schema FK scanner is a real gate - an FK from the new tables into any other schema fails the build.
- Pseudonymous keys are one-way hashes. Never store the raw identity reference, and never store anything clinical, in this schema.
- Downstream, #725 recomputes the daily aggregate in full rather than incrementing it, because that is what makes a late-arriving doctor edge idempotent. Write the table so full-row upsert is natural.
- Blockers: #718 (shared integration fixture), #719 (event identity + trace), #722 (draft metering). All three are prerequisites for the `draft`-appears-as-a-produced-task-type criterion.
