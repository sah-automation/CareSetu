# Brief - PHASE-1 T2a Envelope + transactional outbox writer

**Ticket:** #19 · **Parent:** #16 · **Refreshed:** 2026-08-10
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

The typed event `Envelope` (`event_id`, `event_type`, `schema_version`, `occurred_at`, `producer`, `payload`) and the transactional outbox writer that inserts a `pending` outbox row in the same DB transaction as a state change. An integration test publishes an envelope into a throwaway outbox (via the Phase 1 helper) and asserts a pending row.

Acceptance criteria:

- [ ] `Envelope` validates its fields (UUID `event_id`, `domain.action` `event_type`, typed payload)
- [ ] Writer inserts a `pending` outbox row atomically with the caller's transaction
- [ ] Integration test: publish -> one pending row in a throwaway outbox
- [ ] No business events are added to the event registry

## Read-list (in order)

1. Issue #16 Implementation Decisions - Envelope fields + outbox row contract (columns, status machine) (~1K).
2. `docs/adr/0002-transactional-outbox-as-async-seam.md` - the outbox seam contract (~0.5K).
3. `docs/standards/coding-standards.md` §3/§4 - typing rules and the same-transaction outbox write (~0.5K).
4. Brief from #18 - the DDL template/helper surface to publish into (~0.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`, any module internals.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run lint`

## Done-verify (acceptance criteria → commands)

- `npm run test:integration` (new publish test passes)
- `npm run test:unit:backend`

## Handoff notes

- `Envelope` is Pydantic v2; no raw dicts cross the seam (coding-standards §3).
- Rows start `pending`; only the dispatcher moves them out (ADR-0002).
- Do not add any `FEAT-*` event names to the registry in `internal-modules.md` §4.2 - none exist yet.
- Baselines verified green on 2026-08-10.
