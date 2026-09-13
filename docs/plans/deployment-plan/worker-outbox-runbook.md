# Operator Runbook - Single worker, stranded-intake repair, in-flight claim recovery

**Ticket:** #394 (parent #388) · **Last updated:** 2026-09-12
**Applies to:** the outbox/dispatcher async seam (ADR-0002, ADR-0003) - `apps/backend/bus/dispatcher.py`, `apps/backend/worker/main.py`, and every module's `<module>_outbox` table.

This runbook codifies the operational discipline the duplicate-worker incident (#388) demanded. Three rules, in order of importance:

1. **Exactly one worker process polls any module outbox.** A second worker must never be started.
2. **A capture event dead-lettered by a now-fixed bug is repaired by re-enqueueing it** - the pipeline re-runs under the fixed code, leaves Captured, and can never dead-letter again: it transcribes to Ready for Review, degrades to Ready for Review, or (only for an unusable transcript) moves the intake to Re-record.
3. **Outbox claims left in-flight by a crashed or duplicate worker are recovered** - the surviving worker's lease recovery is the primary mechanism; any residual rows with expired leases are manually re-pended.

The contract to preserve: **no intake is left at Captured and no queued event is silently dropped.**

---

## 0. Concepts - what the machinery actually does

Read this section once; every procedure below is just these facts applied.

- **Outbox row contract** (`bus/outbox_ddl.py`): `id` (UUID PK), `event_id`, `event_type`, `payload`, `occurred_at`, `status`, `attempts`, `next_attempt_at`. Status machine: `pending -> inflight`, and terminal `dead_letter` at the attempt cap. A fully delivered row is **deleted** (ADR-0002, no tombstone); the subscriber's own `consumed_events` ledger is the delivery record.
- **Claim** (`claim_pending_rows`): the poll loop flips eligible `pending` rows to `inflight` with `next_attempt_at = now + claim_timeout` (default `60s`, `DispatcherConfig.claim_timeout_seconds`). The commit happens before any handler runs, so a crash after claim leaves the row to be reclaimed after the timeout. The claim query uses `SELECT ... FOR UPDATE SKIP LOCKED`, so two workers never claim the same row at the same instant.
- **Lease recovery** (`reclaim_stale_inflight`): the first step of every `process_outbox_table` pass re-pends every `inflight` row whose `next_attempt_at` has passed (`status='inflight'`, `next_attempt_at IS NOT NULL`, `next_attempt_at <= now()`, set `status='pending'`, `next_attempt_at=NULL`). Reclaim and claim share one transaction, so re-pended rows are immediately claimable. This is the surviving worker's automatic recovery path.
- **Delivery + ledger** (`bus/handler_harness.run_handler`, `bus/ledger.record_consumed_event`): a handler runs ledger-first in ONE transaction - `record_consumed_event` inserts the `event_id` into the subscriber's own `consumed_events` (its own schema, ADR-0003), then the handler effects commit together. A raising handler rolls back the whole transaction, including the ledger row. A replay of an already-delivered `event_id` finds its ledger row and is a no-op.
- **Failure / dead-letter** (`record_failed_attempt`): a partial fan-out increments `attempts` and schedules an exponential-backoff retry, or marks `dead_letter` once the count reaches `max_attempts` (default `5`). `intake.captured` has exactly one subscriber (`modules/intake/adapters/__init__.py:123`), so a dead-lettered capture row means that single handler failed on every attempt.
- **Failing handler semantics specific to intake** (`modules/intake/adapters/pipeline.py`): the pipeline never raises for a degradable condition - it degrades to raw doctor review instead (missing consent, transcribe failure, structure failure; the NFR-001 budget meter is observe-and-warn PS-10 and never degrades - an exhausted budget is logged and the pipeline proceeds). A degraded run commits normally (ledger + effects), so the intake reaches `ready_for_review` and the outbox row is deleted. The one forward move that is not `ready_for_review`: a successfully transcribed but **unusable** transcript transitions the intake to `re_record` (the patient is asked to re-record; forced-text fallback at the attempt cap reaches `ready_for_review`). Either way the intake leaves `captured` - it is never stranded and never dead-lettered. **A handler raise is now reserved for unexpected bugs** - which is why strandings like the #388 incident are a one-time repair, not an ongoing class.

---

## 1. Rule 1 - Exactly one worker process

### The rule

Across the whole deployment, exactly **one** dispatcher run-loop may poll the module outboxes. A second must not be started.

Today the run-loop lives in the standalone worker process `apps/backend/worker/main.py` (`python -m worker.main` from `apps/backend`) - the composition root that builds the `HandlerRegistry`, discovers the module outboxes over `MODULE_SCHEMAS`, and runs `run_poll_loop`. The FastAPI app (`app.main`) does **not** run the dispatcher in its lifespan; its lifespan only inits Redis clients.

### Why

- The transport is **at-least-once with per-subscriber ledger dedupe** - correct with one delivery loop, and still correct with two. The problem is aggregate contention, not duplicate delivery:
  - Two poll loops racing `reclaim_stale_inflight` + `claim_pending_rows` thrash leases: worker A claims a row, its claim lapses mid-delivery, worker B's reclaim picks it up, A's guarded delete/failure-update then no-ops with "re-claimed by another worker" logs (the guard on `status` + `next_attempt_at` in `delete_outbox_row` / `record_failed_attempt`).
  - In the #388 incident the same contention left claims stuck in-flight, and a voice intake's `intake.captured` row dead-lettered after repeated transcribe-leg failures across the two processes.
- Killing or restarting a worker does **not** lose events: its in-flight claims are re-pended by the survivor's reclaim after `claim_timeout`, and a queued `pending` row is simply delivered by whichever worker claims it. No event is ever silently dropped by having fewer workers. The only safe scale-up is scale-out of the API/uvicorn (stateless), never of the poll loop.

### Enforcement

- **Never** start a second worker. The VM path runs it as one systemd unit (`portfolio-deployment-plan.md` §8 maps the deferred worker to exactly that unit); the Render port is a separate process in a process manager.
- **Verify** before and during an incident, and after any deploy/restart:

  ```
  # Linux/staging VM - exactly one python -m worker.main process
  pgrep -af "worker.main"                 # expect exactly one line
  # When the VM path wraps the worker in systemd: list units, expect exactly
  # one active + enabled unit running worker.main (a concrete .service file is
  # not committed to the repo - it is created during VM provisioning).
  systemctl list-units 'worker*'

  # Render (if ever moved off the deferred worker note) - one web service
  # instance running the worker; never a second process in a separate service.
  ```

- **Do NOT** run the dispatcher both in-process (FastAPI lifespan) and as a standalone process. That is two poll loops by definition. If the in-process option is ever adopted, the app must run at `uvicorn --workers 1` with the worker process removed, and both must never coexist.

- **If a duplicate is ever detected** (the incident class): stop one worker immediately (SIGTERM → graceful drain of its current pass), keep exactly one, then run Rules 2 and 3 to repair anything left stranded.

---

## 2. Rule 2 - Stranded-Captured repair (dead-lettered capture event)

### Symptom

An intake submitted by a patient never moves past **Captured**: the status page shows the intake still processing, and it stays there. The cause is a `dead_letter` `intake.captured` row in `intake.intake_outbox` whose single subscriber (the AI pipeline) failed every one of the `max_attempts` delivery attempts under the buggy code.

### Detect - is this the case?

Run against the database (psql, direct connection):

```sql
-- The stranded intakes: still Captured, with a dead-lettered capture event.
SELECT i.id AS intake_id,
       dl.event_id,
       dl.attempts,
       dl.occurred_at,
       dl.next_attempt_at
FROM intake.intake_intakes i
JOIN intake.intake_outbox dl
  ON dl.payload->>'intake_id' = i.id::text
WHERE i.status = 'captured'
  AND dl.event_type = 'intake.captured'
  AND dl.status = 'dead_letter';

-- No pre_summary may exist for these intakes (a stranded intake has none).
SELECT i.id AS intake_id
FROM intake.intake_intakes i
JOIN intake.intake_pre_summaries p ON p.intake_id = i.id
WHERE i.status = 'captured';
```

Sanity checks before repairing:

- The intake really is `captured` - not `structuring`, `re_record`, `ready_for_review`, or `failed`. The pipeline only runs from `captured`; a row already past it must not be re-run (the pipeline would log "not captured; skipping AI pipeline" - a harmless no-op, but skip the repair).
- No `pre_summary` row exists for it (the pipeline never committed one for a failed run).
- The dead-letter reason is the pre-fix class (transcribe-leg provider rejection on every attempt), not an active new bug that would dead-letter again.

### Why re-enqueueing the SAME event_id is the repair (pinned semantics)

The brief's crux question is settled by the code: **a dead-lettered `intake.captured` row has NO committed `intake.consumed_events` ledger row for its `event_id`.** `run_handler` wraps `record_consumed_event` and the whole pipeline in one transaction (`engine.begin()`); every delivery attempt raised (the pre-#393 transcribe leg raised `Ext002CallError` on the multipart payload), so each attempt rolled the transaction back - the ledger insert, the intake status flip, the `ai_jobs` row, and any pre_summary all rolled back together. The intake therefore sits untouched at `captured`, and the ledger has no record of the event.

Re-publishing the **same `event_id`** as a fresh outbox row is therefore:

- **Not a replay** - the subscriber's ledger is empty for that id, so `record_consumed_event` inserts a new ledger row and the pipeline runs.
- **Safe under the pathological case** - if a ledger row somehow existed (say a delivered event requested twice), the replay is a no-op skip, so the same id can never double-run the pipeline. There is exactly one subscriber, so there is no sibling ledger to preserve either.
- **Deleting the old `dead_letter` row is optional.** Keeping it preserves the audit trail of the original failure. Only a new `pending` row is inserted.

The re-run runs under the **fixed code (#393)**: when the ASR provider is healthy the intake transcribes and structures to `ready_for_review`; when the provider is down, a media-read fails, consent is missing, or the budget is exhausted, the pipeline degrades to raw doctor review and still reaches `ready_for_review`; a transcribed-but-unusable transcript moves the intake to `re_record` instead. Every one of these is a normal commit (no raise) with the outbox row deleted - the run **cannot dead-letter again**, and the intake is never left silently at `captured`.

### Repair procedure

For each stranded intake:

1. Confirm the `captured` status and missing pre_summary (detect queries above). Note the intake's `event_id` - this is the **capture** event id from the dead-lettered row, NOT a new uuid.
2. Re-enqueue that capture event as a fresh `pending` row with the **same `event_id`**:

```sql
-- One intake at a time. event_id below is the uuid from the detect query.
INSERT INTO intake.intake_outbox (id, event_id, event_type, payload, occurred_at, status, attempts, next_attempt_at)
SELECT gen_random_uuid(), event_id, event_type, payload, occurred_at, 'pending', 0, NULL
FROM intake.intake_outbox
WHERE status = 'dead_letter'
  AND event_type = 'intake.captured'
  AND event_id = '<the captured event_id uuid>';
```

- The new row's `id` is a fresh uuid (the old `dead_letter` row still owns its `id`); the `event_id` is deliberately the original capture event id. `occurred_at` is kept from the original so ordering and polling order are preserved.
- `attempts=0` and `next_attempt_at=NULL` make the row eligible on the very next poll (the eligibility predicate accepts `NULL` `next_attempt_at`).
- Run it once per stranded intake. Re-running the same `INSERT` twice creates two identical `pending` rows - both claimable, both with the same `event_id`; the first delivery ledger-commits, the second is a no-op skip. Harmless (at-least-once), but avoidable - check the count first.

3. Let the worker poll. Within `poll_interval_seconds` (default `1s`) the row is claimed and the pipeline runs (transcribe + structure, minutes for a real clip). The pipeline finishes by reaching `ready_for_review` (or `re_record` on an unusable transcript); the outbox row is deleted after full fan-out.
4. Verify per Rule 4 (below).

### Never do any of this

- **Never hand-edit the intake status** (`intake.intake_intakes.status`) to force it past Captured. The pipeline owns that transition and re-runs it cleanly from a re-enqueued event.
- **Never manually insert a `pre_summary` or `ai_jobs` row.** Those are pipeline effects, produced only by a real run.
- **Never flip the dead-letter row back to `pending` in place** (`UPDATE intake.intake_outbox SET status='pending' WHERE ...`). The row is terminal by design and its `id`/`occurred_at` are already used; a fresh row with the same `event_id` is the repair. (The only exception is the controlled manual re-pend in Rule 3, which targets `inflight` rows, never `dead_letter` rows.)
- **Never delete the intake or the dead-lettered row to "clear" the queue.**

---

## 3. Rule 3 - In-flight claim recovery (crashed or duplicate worker)

### Symptom

Rows stuck at `inflight` with a `next_attempt_at` in the future (a live claim by a process that died without completing) or in the past (an expired lease) - from a worker killed without drain, or from the two-worker thrash of the incident.

### Auto-recovery first - rely on the survivor

The surviving worker already does the recovery. Every `process_outbox_table` pass begins with `reclaim_stale_inflight` (same transaction as the claim step): any `inflight` row whose `next_attempt_at` has passed is re-pended to `pending` with a `NULL` `next_attempt_at`, and the very same pass then claims and delivers it. So:

1. Confirm a healthy single worker is up (Rule 1).
2. Wait at least `claim_timeout_seconds` (default `60s`) past the row's `next_attempt_at` and let the worker complete its poll passes.
3. Observe: the expired `inflight` rows flip to `pending` and are then deleted after successful redelivery (or retried through the normal backoff).

```sql
-- Watch the recovery. One statement per module outbox (11 modules in
-- bus/bootstrap.py: iam, partner, health, consent, intake, care,
-- diagnostics, fulfillment, settlement, notify, audit). The point is to
-- confirm each table's inflight count drains to zero after the survivor's
-- reclaim passes.
SELECT status, count(*) AS rows
FROM <schema>.<module>_outbox
GROUP BY status;
```

Example for the incident-affected table: `SELECT status, count(*) FROM intake.intake_outbox GROUP BY status;`. Repeat for every module outbox, or wrap the loop in a `DO` block with `format('SELECT status, count(*) FROM %I.%I GROUP BY status', schema, table)` over the discovered `*_outbox` tables - the exact inventory tooling is at your discretion; what matters is that `inflight` reaches zero.

### Manual reset - only the residual rows with expired leases

When inflight rows remain **after** the survivor's reclaim passes and their lease is genuinely expired, re-pend them by hand. Use exactly the same predicate `reclaim_stale_inflight` uses (guarded, narrowing, idempotent):

```sql
-- Residual expired-lease rows ONLY. One statement per affected table,
-- or a loop over each module schema's <module>_outbox table.
UPDATE <schema>.<module>_outbox
SET status = 'pending',
    next_attempt_at = NULL
WHERE status = 'inflight'
  AND next_attempt_at IS NOT NULL
  AND next_attempt_at <= now();
```

For the intake incident table this is `UPDATE intake.intake_outbox ...` with the same WHERE shape. **Lockstep rule:** this statement mirrors `reclaim_stale_inflight` (dispatcher.py) verbatim; if that predicate ever changes, update this SQL in the same change - the dispatched code is the source of truth, and a drifted copy would both miss rows and under-cut the guard. Criteria to hold before issuing it:

- The row's `next_attempt_at <= now()` - an **expired** lease. Never re-pend an unexpired claim; that would resurrect delivery a live handler is mid-way through and clobber the first worker's guarded delete/failure write (the very guard that protects slow workers).
- The claiming worker is confirmed gone (process check under Rule 1) - not merely slow.
- A single worker is up to actually claim and deliver the re-pended rows.

Re-pended `pending` rows are delivered on the next poll under at-least-once: each subscriber's ledger dedupe guarantees exactly-once effects even if a claim raced.

### What recovery means for "no silent drops"

A `pending` row is never dropped: it is polled until delivered or dead-lettered with an alert log. An `inflight` row is never dropped: it is re-pended after its lease expires. The only "deliberate" loss is a dead-lettered row, and that path is precisely what Rule 2 repairs. Do not delete outbox rows by hand to "clean the queue" - a deleted row with no ledger entry destroys the only pending signal that the event still needs handling.

---

## 4. Manual verification record

Every repair is verified against the live stack, never against a test seam. The checks below are the verification procedure.

### Verification checks

| #   | Check                             | Command / query                                                                                                               | Expected                                                                                                                                               |
| --- | --------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 1   | Exactly one worker                | `pgrep -af worker.main` (or systemctl on the VM path)                                                                         | Exactly one process line                                                                                                                               |
| 2   | Repaired intake leaves Captured   | `SELECT id, status FROM intake.intake_intakes WHERE id = <intake_id>;`                                                        | `ready_for_review` (or `re_record` when the transcript was unusable)                                                                                   |
| 3   | No intake left at Captured        | `SELECT count(*) FROM intake.intake_intakes WHERE status = 'captured';`                                                       | `0` (or only intakes still in the processing window)                                                                                                   |
| 4   | Capture event delivered, row gone | `SELECT status FROM intake.intake_outbox WHERE event_id = '<event_id>' AND status = 'dead_letter';` plus the de-dupe evidence | Old `dead_letter` row may remain (kept history); no new `pending`/`inflight` row remains                                                               |
| 5   | In-flight recovery drained        | Per-schema `inflight` counts (Rule 3 inventory query)                                                                         | Every `<module>_outbox` `inflight` count = 0                                                                                                           |
| 6   | Exactly one pre-summary           | `SELECT count(*) FROM intake.intake_pre_summaries WHERE intake_id = <intake_id>;`                                             | `1` (or `0` when the intake degraded to raw review or moved to re-record)                                                                              |
| 7   | AI job reflects the run           | `SELECT task_type, status FROM intake.intake_ai_jobs WHERE intake_id = <intake_id> ORDER BY id;`                              | A `completed` `structure` job on the healthy path; a failed `transcribe`/`structure` job + a degraded review only when the provider was genuinely down |

### Record (ticket #394 - #388 acceptance gate)

Semantic backing was re-verified on **2026-09-12** via `npm run test:unit:backend` (1729 passed, 3 pre-existing failures unrelated to intake; dispatcher + worker suites green). The pipeline semantics the repair rests on (ledger + effects one transaction, single subscriber, dead-letter = no ledger row) are pinned by that suite. The live-stack execution row below is the ticket's closing gate:

| Date | Operator | Environment | Exactly-one-worker | Ready for Review | Captured count | In-flight drained | Notes                                                                                                                                |
| ---- | -------- | ----------- | ------------------ | ---------------- | -------------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
|      |          |             |                    |                  |                |                   | _Run the detection and repair queries from Rules 1-3 above against staging/production; fill each column after the repair completes._ |

---

## 5. Where the rules are enforced in code (reference)

- Dispatcher claim/lease/dead-letter mechanics: `apps/backend/bus/dispatcher.py` - `claim_pending_rows`, `reclaim_stale_inflight`, `record_failed_attempt`, `process_outbox_table`.
- Single-run-loop composition root: `apps/backend/worker/main.py` - `run_worker_until_stopped`, SIGTERM/SIGINT drain wiring.
- Re-enqueue mechanics: `apps/backend/bus/outbox_writer.py` (`write_outbox`), `apps/backend/bus/ledger.py` (`record_consumed_event`).
- Ledger-first one-transaction handler boundary: `apps/backend/bus/handler_harness.py` (`run_handler`).
- Single subscriber for `intake.captured`: `apps/backend/modules/intake/adapters/__init__.py` (`register_handlers`).
- Fixed pipeline that transcribes-or-degrades: `apps/backend/modules/intake/adapters/pipeline.py` (`_run_structuring_pipeline`, ticket #393).
