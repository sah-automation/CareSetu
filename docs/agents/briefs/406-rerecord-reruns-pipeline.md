# Brief - 406 T09 Re-record re-runs the structuring pipeline

**Ticket:** #406 · **Parent:** #397 · **Refreshed:** 2026-09-13
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

A re-recorded intake never stalls in `structuring`. The `intake.retry_requested` consumed-event handler becomes a real pipeline re-trigger. The pipeline entry accepts an intake already in `structuring` (a retry arrives there after the facade's Re-record to Structuring transition) and runs it exactly like a first take, while the ledger keeps redelivery idempotent. The captured-path guard stays strict, so a replayed `intake.captured` on an in-flight intake still skips. The re-recorded clip (`media_refs`) and the incremented record attempt flow into the run; the completed job and pre-summary are tied to that attempt count. Acceptances: the handler re-runs the pipeline (no bare no-op, coding-standards §8); pipeline entry accepts an intake already in `structuring` with the captured-path guard strict; new clip + attempt count flow in; consumer-boundary and facade/transition tests cover re-record to ready_for_review with a new pre-summary.

## Read-list (in order)

1. `modules/intake/adapters/__init__.py` - `_on_intake_retry_requested` (:180-192, the drain to implement) and `_on_intake_captured` (:158-177, the ledger-first pattern + captured-path guard) (~2K)
2. `modules/intake/adapters/pipeline.py` - `_run_structuring_pipeline` entry (:143-185, the START_STRUCTURING transition) - must tolerate arriving already in `structuring`; the RECORD_UNUSABLE/RE_RECORD path (:317-352) that emits `intake.retry_requested` (~4K)
3. `modules/intake/facade.py` - `re_record_intake` (:296-407) - the Re-record to Structuring transition, attempt increment, media ref persistence, and the `intake.retry_requested` emission the handler consumes (~2K)
4. `modules/intake/domain/state_machine.py` - `IntakeStatus`/`IntakeAction`/`_LEGAL_TRANSITIONS` (:139-205) - where the attempt-cap and guards live (~1.5K)
5. Tests: `test_intake_pipeline_consumer.py`, `test_intake_pipeline_degradation.py`, the intake facade/route and transition-matrix tests (~1K skim)

## Do NOT read

- Pricing/usage plumbing (#398/#399), budget gating (#408), middleware (#403), frontend sources, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1732 passed (verified 2026-09-13)
- `npm run typecheck:backend` - mypy strict clean
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - consumer harness: retry handler re-runs the pipeline from `structuring`; a replayed `intake.captured` on an in-flight intake still skips; facade/transition tests cover re-record to `ready_for_review` with a new pre-summary

## Handoff notes

- `coding-standards` §8 forbids bare no-op bodies - the `del connection, payload` drain is exactly the finding (#397 PS-07)
- The move that matters: START_STRUCTURING must not throw when the intake is already `structuring` (facade already transitioned it); idempotency stays on the ledger dedupe
- Tie the completed job and pre-summary to the intake's incremented `record_attempts`/new `media_refs`, not the original capture
