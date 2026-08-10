# Brief - PHASE-1 T2c Outbox round-trip integration test

**Ticket:** #21 · **Parent:** #16 · **Refreshed:** 2026-08-10
**Reading surface:** ~2.5K tokens (budget 10K) - within budget

## Scope

The Phase 1 definition-of-done for the async seam: an end-to-end **round-trip** integration test against the local native PostgreSQL - publish -> dispatch/fan-out -> subscriber ledger -> replay the same `event_id` -> assert exactly one ledger row. A throwaway schema/outbox/ledger is materialized via the shared Phase 1 helper.

Acceptance criteria:

- [ ] Round-trip test publishes, dispatches, and records one ledger row
- [ ] Replaying the same `event_id` leaves exactly one ledger row
- [ ] Test runs against the local native PostgreSQL with no Docker

## Read-list (in order)

1. Issue #16 Testing Decisions - the round-trip seam description (~1K).
2. `docs/adr/0002-transactional-outbox-as-async-seam.md` - what the round-trip proves (~0.5K).
3. `tests/integration/conftest.py` - the fixture patterns to reuse (~0.5K).
4. Briefs from #18/#19 - the helper + writer + dispatch surface to compose (~0.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:integration` (round-trip passes)

## Handoff notes

- The integration suite skips cleanly when the native PG is unreachable (conftest pattern); locally it targets the `caresetu` native service.
- The round-trip uses a synthetic event (`phase1.round_trip`) in a throwaway schema - no real module, no registry addition.
- This is the contract that #22 (T3a) and #23 (T3b) extend; keep the test as the seam's external-behavior proof.
- Baselines verified green on 2026-08-10.
