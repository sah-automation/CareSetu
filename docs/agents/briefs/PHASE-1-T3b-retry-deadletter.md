# Brief — 23 PHASE-1 T3b: Retry/backoff + dead-letter + failure isolation

**Ticket:** #23 · **Parent:** #16 · **Refreshed:** 2026-08-11
**Reading surface:** ~10K tokens (budget 10K) — within budget

## Scope

Failure semantics on the dispatcher: per-subscriber failure isolation (one
failing subscriber does not stall the rest), exponential-backoff retries capped
at 5 attempts, then `dead_letter` status with an alert/log line. Integration
tests prove a failing handler retries then dead-letters while a healthy sibling
subscriber still receives the event.

Acceptance criteria (verbatim from #23):

- [ ] A failing subscriber's delivery retries with exponential backoff, capped at 5 attempts
- [ ] After the cap the row is `dead_letter` and an alert/log line is emitted
- [ ] One subscriber's failure does not prevent other subscribers from receiving the event
- [ ] Success for one subscriber does not depend on another subscriber's outcome

Out of scope: config errors (no payload model / no handlers / dispatch raising)
keep T3a behaviour — logged and left on the reclaim path, never counted as a
subscriber attempt.

## Read-list (in order)

1. Issue #16 `Implementation Decisions` — the 5-attempt dead-letter contract,
   per-subscriber success semantics, transport-only rule (~2K, via `gh issue view 16`).
2. `apps/backend/bus/dispatcher.py` — the loop internals to extend:
   `process_outbox_table` (the partial-failure `else` branch that currently
   leaves the row `inflight` to age into reclaim), `claim_pending_rows` (the
   RETURNING that must now carry `attempts`), `DispatcherConfig`, `OutboxRow`,
   `delete_outbox_row`'s claim guard to mirror, and the module docstring whose
   T3b forward-reference becomes this ticket (~2.5K).
3. `apps/backend/bus/dispatch.py` — `DispatchResult.all_succeeded` /
   `HandlerOutcome`: the partial-failure signal the retry path keys on (~0.5K).
4. `apps/backend/bus/outbox_ddl.py` — `OUTBOX_STATUS_*` constants (incl.
   `dead_letter`), the `attempts` column the row already carries (~0.5K).
5. `tests/integration/test_dispatcher.py` + `tests/integration/conftest.py` —
   the T3a poll/claim/ledger fixtures and the `test_partial_failure_*` test that
   changes semantics under T3b (~3K).
6. `tests/unit/test_dispatcher.py` — the pure-contract test pattern for the new
   backoff/decision helpers (~0.5K).
7. `docs/standards/error-handling-observability.md` — the dead-letter alert line
   shape (structured, no PHI) (~0.5K).

## Design seams already settled in code (conform, don't relitigate)

- **Retry state is `pending`, not `failed`.** T3a's claim-eligibility predicate
  is `status='pending' AND (next_attempt_at IS NULL OR next_attempt_at <=
now())`. Backoff scheduling composes with it by returning a failed row to
  `pending` with `next_attempt_at = now + backoff` - there is no `failed`
  outbox status.
- **Attempt counting:** `attempts` starts at 0 (writer). Each partial/failed
  fan-out increments it; the row dead-letters when the incremented count reaches
  `max_attempts` (5). A row survives 5 delivery attempts (initial + 4 retries).
- **Exponential backoff:** `delay = backoff_base_seconds * 2**(attempt-1)` where
  `attempt` is the 1-based count after the increment. Pure, unit-testable.
- **Claim guard on the retry/dead-letter update:** mirror `delete_outbox_row` —
  `UPDATE ... WHERE id=:id AND status='inflight' AND next_attempt_at =
:claimed_deadline` so a slow worker cannot clobber a sibling's re-claimed row.
- **Alert line:** structured `logger.error` naming `event_id`, `event_type`, and
  the attempt count — no payload content (no PHI).
- **`TablePollResult` gains `retried` and `dead_lettered` counters** (additive)
  so integration tests can assert the transitions.

## Do NOT read

- `docs/archive/`, `phase0/`, the frontend, the CI workflow, migration files.
- T4 (#30) worker entrypoint, `run_poll_loop` stop semantics, gateway stubs.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:integration` (new T3b tests: retry-then-dead-letter, healthy
  sibling still receives, capped at 5, `next_attempt_at` backoff)
- `npm run test:unit:backend` (backoff delay + retry-status helpers)
- `npm run typecheck:backend` and `npm run lint:backend`

## Handoff notes

- Baseline verified green on 2026-08-11: 198 unit + 17 integration passed.
- T3a (#22) already ships per-subscriber isolation in `dispatch` (one failing
  handler never stops its siblings) and the honest at-least-once fallback (a
  partial fan-out stays `inflight` and ages into stale-reclaim). T3b replaces
  that fallback with explicit attempts/backoff/dead-letter bookkeeping.
- The `test_partial_failure_leaves_row_inflight_not_deleted` integration test is
  T3a semantics; under T3b a partial fan-out schedules a backoff retry
  (`pending`, attempts=1, future `next_attempt_at`) — update it.
- Existing config-error tests (`test_row_without_registered_payload_model_*`,
  `test_row_with_no_registered_handlers_*`) must stay green untouched: those
  paths keep leaving the row on the reclaim path without counting attempts.
