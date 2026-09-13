# Brief - 394 Single-worker runbook + stranded-intake repair procedure

**Ticket:** #394 · **Parent:** #388 · **Refreshed:** 2026-09-12
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

An operator runbook codifying the single-worker rule and recovery for the two stranded-state classes caused by the duplicate-worker incident: (1) exactly one worker process polls the module outboxes - a second must not be started; (2) an intake stranded at Captured by a dead-lettered capture event is repaired by re-enqueuing its capture event so the pipeline re-runs under the fixed code (it will transcribe or degrade, never dead-letter again); (3) outbox claims left in-flight by a crashed or duplicate worker are recovered by relying on the surviving worker's lease recovery, then manually resetting any residual rows with expired leases. No intake is left at Captured and no queued event is silently dropped. Verified manually against the live stack, not a test seam.

Acceptance criteria:

- [ ] Runbook documents: exactly one worker process polls any module outbox
- [ ] Runbook documents the stranded-Captured repair: re-enqueue the intake's capture event; the re-run reaches Ready for Review (transcribe or degrade, never dead-letter)
- [ ] Runbook documents in-flight claim recovery: surviving worker's lease recovery first, then manual reset of residual expired-lease rows
- [ ] Manual verification recorded: repaired intake re-runs to Ready for Review, no intake left at Captured, exactly one worker running

## Read-list (in order)

1. `apps/backend/bus/dispatcher.py` - `claim_pending_rows` (pending->inflight claim with `next_attempt_at`), `reclaim_stale_inflight` (surviving-worker lease recovery), `retry_status_after_failure` and the dead-letter cap, `process_outbox_table`/`run_poll_loop` - the exact claim/lease/dead-letter semantics the repair procedures rest on (~2K)
2. `apps/backend/worker/main.py` - the single long-running composition root: outbox discovery over module schemas, signal handling, the scheduler - what "exactly one worker" means concretely (~0.8K)
3. `apps/backend/bus/outbox_writer.py` (`write_outbox`) and `apps/backend/bus/ledger.py` (`record_consumed_event`) - the re-enqueue mechanics and the subscriber-ledger de-dupe that makes re-delivery safe or a no-op (~0.5K)
4. `docs/plans/deployment-plan/portfolio-deployment-plan.md` (the worker-deferred note) and the post-phase-14 observability plan's deferred horizontal-scaling note - where the runbook text lands (~0.7K)

## Do NOT read

- AI gateway adapters · frontend · domain state machines · `docs/archive`

## Baseline verify (must pass before the first edit, verified 2026-09-12)

- `npm run test:unit:backend` - 1723 passed, 3 pre-existing failures unrelated to intake (listed in sibling briefs); dispatcher + worker suites green

## Done-verify (acceptance criteria → commands)

- Manual ops verification against the live stack per the acceptance criteria (repaired intake reaches Ready for Review; no intake left at Captured; exactly one worker running)
- `npm run test:unit:backend` stays green (no code required unless a repair helper is added - keep any helper script-only, not app code)

## Handoff notes

- Blocked by #393: the repair must be documented against the fixed pipeline (transcribe-or-degrade under fixed code). A re-run before #393 would re-300-style-fail against the ASR provider.
- Pinning the repair semantics is the crux of this ticket. Work out against the dispatcher/ledger code which of these is true, then document precisely:
  - A dead-lettered capture event was NEVER ledgered (the ledger write and handler effects are one transaction; a failing handler rolled back), so re-publishing the same event id is a fresh outbox row and re-runs the pipeline - OR
  - If the event WAS ledgered, replay is a no-op, so the repair must emit a new event id (e.g. a re-issued `intake.captured`-equivalent) rather than re-publishing the same id.
- The dispatcher already reclaims stale inflight (`claim_timeout` + `reclaim_stale_inflight`): the surviving worker clears crashed/duplicate-worker claims on its next poll. Residual rows with expired leases that reclaim misses are reset manually - document the exact SQL/criteria.
- The design is a single worker; this ticket's runbook is the operational enforcement of that design. No CI/CD or deployment-harness changes beyond the runbook.
