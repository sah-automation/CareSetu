# Brief - 22 PHASE-1 T3a: Dispatcher poll loop + inflight claim

**Ticket:** #22 · **Parent:** #16 · **Refreshed:** 2026-08-11
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

The dispatcher poll loop over discovered outbox tables: durable inflight claim
(`UPDATE ... SET status='inflight' WHERE status='pending' RETURNING`),
stale-inflight reclaim after a timeout, and delete-on-full-success. Integration
tests prove the loop drains pending rows, reclaims stale inflight rows, and
deletes rows after successful fan-out.

Acceptance criteria (verbatim from #22):

- [ ] Loop polls all discovered outbox tables (list-based discovery, not hardcoded modules)
- [ ] Rows are durably claimed `inflight` before handlers run
- [ ] Stale `inflight` rows are reclaimed after the timeout
- [ ] Rows are deleted after full successful fan-out (no tombstone)
- [ ] The dispatcher touches outbox tables only, never domain tables (transport-only)

Out of scope (belongs to #23 T3b): attempts/backoff, `dead_letter`, retry
scheduling. On a partial fan-out the row stays `inflight` and ages into the
stale-reclaim path - retry mechanics are #23's job.

## Read-list (in order)

1. Issue #16 `Implementation Decisions` + `Testing Decisions` - the dispatcher
   claim model, row contract, transport-only rule (~3K, read via `gh issue view 16`).
2. `apps/backend/bus/*.py` docstrings - ADR-0002 §1/§2/§3 contract is carried
   in these module docstrings (the ADR file does not exist yet):
   `outbox_ddl.py` (row shape, `status` machine, `next_attempt_at`),
   `outbox_writer.py` (publisher side: pending rows have `next_attempt_at = NULL`),
   `dispatch.py` (the synchronous fan-out step the loop drives; `DispatchResult.all_succeeded`),
   `registry.py` (`HandlerRegistry` - the fan-out targets the loop delivers to) (~2K).
3. `apps/backend/bus/envelope.py` - the `Envelope` fields the loop must
   reconstruct from an outbox row: `event_id`, `event_type`, `occurred_at`,
   `payload` (typed model, never a dict); note the row contract does NOT carry
   `producer` or `schema_version` (~1K).
4. `tests/integration/test_round_trip.py` + `tests/integration/conftest.py` -
   the materialize/publish/ledger fixture patterns to reuse for the T3a
   integration tests (~2K).
5. `docs/standards/coding-standards.md` §2 - module layout the transport must
   not cross (~0.5K).

**Design seams already settled in code** (conform, don't relitigate):

- The loop lives in `apps/backend/bus/` (new `dispatcher.py`) and drives the
  existing `dispatch(registry, envelope)` from `bus/dispatch.py`.
- Claim deadline: reuse the existing `next_attempt_at` column as the
  stale-inflight deadline (set it to `now + claim_timeout` on claim; the writer
  leaves it `NULL` on publish, which also means "eligible now"). Poll
  eligibility is `next_attempt_at IS NULL OR next_attempt_at <= now()`.
- `producer` is not in the row contract; infer it from the outbox schema name.
  `schema_version` keeps its default.
- Payload typing: the loop must deliver a typed `Envelope` (no raw dicts across
  the seam). Give `HandlerRegistry` an additive payload-model registration
  (`register_payload_model` / `payload_model_for`) alongside the existing
  `register`; a row whose `event_type` has no registered payload model is a
  dispatcher error - log and leave the row for reclaim, never delete.
- Delete guard: `DELETE ... WHERE id = :id AND status='inflight' AND
next_attempt_at = :claimed_deadline` so a slow worker cannot delete a row a
  sibling already reclaimed and re-claimed.

## Do NOT read

- `docs/archive/`, `phase0/`, the frontend, the CI workflow, migration files.
- #23's retry/backoff/dead-letter mechanics - T3a only claims, drains, and
  deletes on full success.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:integration` (new T3a integration tests: drain+delete, stale
  reclaim, discovery, transport-only, partial-failure leaves inflight)
- `npm run test:unit:backend` (payload-model registry + envelope reconstruction)
- `npm run typecheck:backend` and `npm run lint:backend`

## Handoff notes

- Baseline verified green on 2026-08-11: 189 unit + 7 integration passed.
- The worker entrypoint that runs this loop is T4 (#30); the loop takes the
  outbox-table list and `HandlerRegistry` as parameters - it must not know
  about modules.
- Partial fan-out in T3a: log a warning, do not delete; the row's
  `next_attempt_at` deadline ages it back through stale reclaim (honest
  at-least-once). #23 layers attempts/backoff/dead-letter on top.
