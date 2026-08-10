# Brief - PHASE-1 T3b Retry/backoff + dead-letter + failure isolation

**Ticket:** #23 · **Parent:** #16 · **Refreshed:** 2026-08-10
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

Failure semantics on the dispatcher: per-subscriber failure isolation (one failing subscriber does not stall the rest), exponential-backoff retries capped at 5 attempts, then `dead_letter` status with an alert/log line. Integration tests prove a failing handler retries then dead-letters while a healthy sibling subscriber still receives the event.

Acceptance criteria:

- [ ] A failing subscriber's delivery retries with exponential backoff, capped at 5 attempts
- [ ] After the cap the row is `dead_letter` and an alert/log line is emitted
- [ ] One subscriber's failure does not prevent other subscribers from receiving the event
- [ ] Success for one subscriber does not depend on another subscriber's outcome

## Read-list (in order)

1. Issue #16 Implementation Decisions - retry/dead-letter + fan-out semantics (~1K).
2. `docs/adr/0002-transactional-outbox-as-async-seam.md` - the 5-attempt dead-letter contract (~0.5K).
3. Brief from #22 - the loop internals to extend (~0.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:integration`

## Handoff notes

- Backoff is exponential; cap is 5 attempts; then `dead_letter` + an alert/log line (ADR-0002).
- Fan-out is per-subscriber independent: a failed delivery counts against that subscriber only; healthy siblings still receive the event.
- Success for one subscriber is never gated on another subscriber's outcome.
- Baselines verified green on 2026-08-10.
