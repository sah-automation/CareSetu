# Brief - PHASE-1 T3a Dispatcher poll loop + inflight claim

**Ticket:** #22 · **Parent:** #16 · **Refreshed:** 2026-08-10
**Reading surface:** ~2.5K tokens (budget 10K) - within budget

## Scope

The dispatcher poll loop over discovered outbox tables: durable inflight claim (`UPDATE ... SET status='inflight' WHERE status='pending' RETURNING`), stale-inflight reclaim after a timeout, and delete-on-full-success. Integration tests prove the loop drains pending rows, reclaims stale inflight rows, and deletes rows after successful fan-out.

Acceptance criteria:

- [ ] Loop polls all discovered outbox tables (list-based discovery, not hardcoded modules)
- [ ] Rows are durably claimed `inflight` before handlers run
- [ ] Stale `inflight` rows are reclaimed after the timeout
- [ ] Rows are deleted after full successful fan-out (no tombstone)
- [ ] The dispatcher touches outbox tables only, never domain tables (transport-only)

## Read-list (in order)

1. Issue #16 Implementation Decisions - dispatcher + claim model (~1K).
2. `docs/adr/0002-transactional-outbox-as-async-seam.md` - dispatcher as pure transport (~0.5K).
3. `docs/standards/coding-standards.md` §2 - the module layout the dispatcher must not cross (~0.5K).
4. Brief from #21 - the dispatch step the loop drives (~0.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:integration`

## Handoff notes

- Claim is a durable `UPDATE ... WHERE status='pending' RETURNING` before any handler runs; the claim must survive a process crash, hence stale-inflight reclaim after a timeout.
- Outbox discovery is list-based (a config list), not a hardcoded set of modules.
- Row is deleted once every subscriber handled it; no tombstone - the subscriber ledger is the delivery record (ADR-0002).
- The dispatcher is transport-only: it never authors events and never reads subscriber ledgers (isolation rule).
- Baselines verified green on 2026-08-10.
