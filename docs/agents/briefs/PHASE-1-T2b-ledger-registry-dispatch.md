# Brief - PHASE-1 T2b consumed_events ledger + HandlerRegistry + dispatch

**Ticket:** #20 · **Parent:** #16 · **Refreshed:** 2026-08-10
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

The idempotent-subscriber `consumed_events` ledger (`event_id` PK) living in the subscriber's own schema, the `HandlerRegistry` mapping `event_type` to its handlers, and the synchronous dispatch/fan-out step that invokes handlers and has them record the ledger. Unit tests prove routing, invocation, and replay-dedupe (same `event_id` -> no second ledger row).

Acceptance criteria:

- [ ] `consumed_events` ledger records `event_id`/`event_type`/`processed_at`/`handler_result`
- [ ] Registry routes one `event_type` to all its registered handlers
- [ ] Dispatch invokes handlers in-process; handler-return-without-exception = success
- [ ] Replaying the same `event_id` is a no-op (single ledger row)
- [ ] The dispatcher never reads subscriber ledgers (isolation rule)

## Read-list (in order)

1. Issue #16 Implementation Decisions - idempotent subscriber + subscriber success semantics (~1K).
2. `docs/adr/0002-transactional-outbox-as-async-seam.md` - the ledger contract (~0.5K).
3. `docs/adr/0003-db-per-module-isolation.md` - the ledger lives with the subscriber, never shared (~0.5K).
4. `docs/standards/coding-standards.md` §2/§3 - module layout and typing (~0.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run lint`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`

## Handoff notes

- The ledger is the subscriber's own delivery record in its own schema - a shared ledger is explicitly rejected (ADR-0002/0003).
- Success = handler returned without exception; the handler writes its own ledger row as part of its own transaction.
- `dispatch` here is the synchronous fan-out step; the poll loop that drives it lands in #22 (T3a).
- Baselines verified green on 2026-08-10.
