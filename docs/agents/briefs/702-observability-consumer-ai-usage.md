# Brief - 702 B4a - Event consumer + idempotency ledger + AI usage aggregates

**Ticket:** #702 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Build MOD-013's event consumer and its exactly-once behaviour: subscribe to `ai_job.completed` and `ai_job.failed`, record the `event_id` in `obs_consumed_events` before applying effects, then accumulate per (date, provider, model, task type) calls, success/failure/timeout, low-confidence count, tokens, cost (paise), and average/p95 duration into `obs_ai_usage_daily`. Replaying the same `event_id` is a no-op and leaves exactly one ledger row. This is the near-real-time input to the cost/quality panels.

### Acceptance criteria

- [ ] Handler registration for `ai_job.completed` / `ai_job.failed` via the existing registry, using the shared `run_handler`/ledger harness.
- [ ] `obs_consumed_events` records `event_id` before effects; a replay of the same event changes nothing and adds no second ledger row.
- [ ] `obs_ai_usage_daily` accumulates the documented columns from the event payload; low-confidence is taken from the event, never recomputed.
- [ ] An outbox round-trip test asserts one aggregate row and exactly-once replay.
- [ ] `npm run typecheck`; `npm run test:unit:backend` pass.

## Read-list (in order)

1. `modules.audit.adapters.register_handlers` - the canonical consumer pattern: `register_payload_model(...)` for owned mirrors, then per-event closures that call `run_handler(envelope, PayloadClass, _impl, "<name>", SCHEMA)`; the `_impl` receives the delivery connection and payload and applies effects ledger-first. Copy this shape exactly for MOD-013. (~3K tokens)
2. `bus.handler_harness.run_handler` - the shared harness: re-validates the payload, opens a NullPool engine/transaction, calls `record_consumed_event`, and skips `_impl` on a replay (`delivered=False`). This is the required seam, not a bespoke loop. (~0.7K tokens)
3. `bus.ledger.record_consumed_event` - the `ON CONFLICT DO NOTHING` on `event_id` returning whether the row was newly written; note it resolves the ledger via `consumed_events_table(schema)`, i.e. the table name is hardcoded `consumed_events`. (~0.5K tokens)
4. `bus.registry.HandlerRegistry` - `register`, `register_payload_model`, `handlers_for`, and the one-handler-per-module-per-type rule that keeps one schema's ledger from conflating sibling subscribers. (~0.6K tokens)
5. `modules.intake.domain.events.AiJobCompletedPayload` / `AiJobFailedPayload` (and `bus.events` constants `EVENT_AI_JOB_COMPLETED` / `EVENT_AI_JOB_FAILED`) - the current payload shape: only `ai_job_id`, `intake_id`, `task_type` (+ `reason` on failed). (~0.8K tokens)
6. The B3 schema models for `obs_ai_usage_daily` and the ledger in `modules.observability` - the exact aggregate columns B4a must write. (~0.5K tokens)
7. The parent plan's §7.3 ("Event consumer") and §8 ("Rollup") - the subscription set, ledger-first ordering, near-real-time accumulation, and the "where an event payload lacks a needed field, register a narrow read-only exception" rule. (~0.8K tokens)
8. A prior async round-trip consumer test in the unit/integration suites (the outbox round-trip harness used by audit/dormant-entry consumers) - the publish -> dispatch -> assert-one-row -> replay shape to reuse. (~1K tokens)

## Do NOT read

- Other event families (`case.*`, `partner.*`, `consent.*`, `record.accessed`, `audit.*`) - those are B4b.
- The frontend.
- Migrations (the schema is B3's).

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS (current tree)
- `npm run test:unit:backend` - PASS (2925 passed)

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck`
- `npm run test:unit:backend`
- The async round-trip test: publish `ai_job.completed`, run the dispatcher, assert exactly one `obs_ai_usage_daily` row and one ledger row; replay the same `event_id`, assert nothing changes and no second ledger row.

## Handoff notes

- Exactly-once comes from the shared harness, not from re-deriving it: `run_handler` already records the ledger row in the same transaction as `_impl`, so B4a only writes the aggregate inside `_impl` on the delivery connection.
- Two pre-existing conflicts must be resolved before implementation, and both were flagged in the B3 brief (#701):
  1. The current `ai_job.*` payloads carry only ids + `task_type`, but B4a must accumulate provider/model/tokens/cost/duration/status from the event, with low-confidence taken from it - never recomputed. Either enrich the `ai_job.*` payloads (no ticket currently owns that; B1's pipeline cost write and the plan's §2 claim both point at it) or apply the plan's §7.3 narrow read-only exception. Resolve before writing the handler so the aggregate column mapping is stable.
  2. Ledger table naming: the harness reads `consumed_events`, the plan/issue name it `obs_consumed_events`. B4a must use the table the harness writes, per acceptance criteria "using the shared `run_handler`/ledger harness".
- Do not reach into `intake.intake_ai_jobs` by cross-schema SQL unless the read-only exception is explicitly registered - aggregation never crosses schemas otherwise.
- Prior art to copy: the audit consumer (`register_handlers` in `modules.audit.adapters`) for registration, and the Phase-1 round-trip harness for the test.
