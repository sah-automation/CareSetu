# Brief - T14 Closed-loop integration test (capture -> pipeline -> review)

**Ticket:** #358 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

The phase slice is proven once end-to-end against a real local PostgreSQL (skipping cleanly when Postgres is unreachable): capture an intake, let the async pipeline structure it via the mock provider against an HTTP stub for EXT-002, and drive the doctor review to finalize - proving the seams (routes, facade, outbox, consumer, budget, consent gate) actually connect, not just pass in isolation.

Acceptance criteria:

- [ ] The closed loop passes with a local Postgres: submit -> intake.captured -> ai job -> pre_summary -> doctor review
- [ ] The suite skips cleanly when Postgres is unreachable (follows `tests/integration/README.md`)
- [ ] EXT-002 is served by an HTTP stub; mock provider used throughout

## Read-list (in order)

1. `tests/integration/README.md` - skip-when-Postgres-unreachable convention (~1K)
2. An existing local-PostgreSQL integration test (e.g. `tests/integration/test_round_trip.py`, `test_dispatcher.py`, `test_harness.py`) - the pattern (~2K)
3. The pipeline (T10/T11), routes (T12) and facade contracts - the seams under test, in contract form only (~3K)

## Do NOT read

- `docs/archive`
- frontend sources
- module internals beyond the seams under test

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1343 passed (verified 2026-09-08)
- `npm run migration-check` - single head green (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:integration` (with local PG reachable)

## Handoff notes

- Test must skip cleanly (not error) when Postgres is unreachable - this suite is not gated by a running DB.
- EXT-002 is an HTTP stub; everything runs against the deterministic mock provider (clean/low knob from T05).
