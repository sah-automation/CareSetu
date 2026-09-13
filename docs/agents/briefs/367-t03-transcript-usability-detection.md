# Brief - 367 T03 Implement transcript usability detection (critical pipeline fix)

**Ticket:** #367 Â· **Parent:** #364 Â· **Refreshed:** 2026-09-09
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

After transcription, the pipeline evaluates transcript quality (empty/short = unusable, moderate = partial, normal = usable) instead of hardcoding `"usable"`. The B3 fallback ladder fires server-side: unusable transcripts trigger `RECORD_UNUSABLE` (below cap: re-record; at cap: forced text). This is the critical fix that makes `re_record_intake` reachable and is the only fix that changes runtime pipeline behavior.

Acceptance criteria (from ticket):

- [ ] Deterministic heuristic: fewer than 5 chars = unusable, 5-20 chars = partial, more than 20 chars = usable
- [ ] Unusable + below attempt cap (1-2): transitions to re_record, emits intake.retry_requested
- [ ] Unusable + at attempt cap (3): transitions to ready_for_review with forced_text=True, emits pre_summary.ready
- [ ] Partial: logs warning, proceeds with structuring (usable but degraded)
- [ ] Hardcoded transcript_usability equals usable line removed from pipeline
- [ ] Unit tests covering all three usability states plus at-cap path

## Read-list (in order)

1. `apps/backend/modules/intake/domain/state_machine.py` - `IntakeStatus`, `IntakeAction.RECORD_UNUSABLE`, `FORCE_TEXT`, `MAX_RECORD_ATTEMPTS` (the cap the ladder branches on) (~1.3K tokens)
2. `apps/backend/modules/intake/adapters/pipeline.py` (post-T01) - `_run_structuring_pipeline` transcribe leg where `transcript_usability` is set; the `TranscribeResult.confidence`/`transcript` fields available (~3K tokens)
3. `apps/backend/modules/intake/domain/events.py` - `intake_retry_requested_envelope`, `pre_summary_ready_envelope` builders the branches emit (~1K tokens)
4. `apps/backend/modules/intake/domain/exceptions.py` - `IllegalIntakeTransitionError` if the transition guard surfaces (~0.4K tokens)
5. Prior art: `tests/unit/test_intake_pipeline_consumer.py` - the mocked-gateway seam used to drive the ladder (`TestIntakePipeline`-style harness returns a canned transcript) (~2K tokens)

## Do NOT read

- `facade.py`, `routes.py`, media store, budget meter
- Frontend sources, `docs/archive/`
- The real EXT-002 provider internals (mock provider is the test seam)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1579 passed (verified 2026-09-09)
- `npm run typecheck:backend` - mypy strict clean (verified 2026-09-09)
- Note: full `npm run typecheck` currently fails only on the stale Next.js generated artifact `.next/dev/types/routes.d.ts` (not source). Ignore it; confirm with `typecheck:backend`.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - new usability-detection tests pass; existing `test_intake_pipeline_consumer.py` and `test_intake_state_machine.py` tests still pass
- `npm run typecheck` clean

## Handoff notes

- Blocked by #365 (T01) - the transcribe leg lives in the extracted `pipeline.py`.
- Highest-risk fix: this changes runtime behavior. Use the mocked AI gateway seam to drive the three usability classes deterministically (return empty string, a short string, a normal string).
- The `RECORD_UNUSABLE` transition itself is already defined in the state machine (was implemented during Phase 7) - this ticket wires it to be reachable. Reuse `transition(current, RECORD_UNUSABLE)` rather than bypassing it.
- At cap, the state machine already yields `READY_FOR_REVIEW` with `forced_text=True`; the pipeline must mirror exactly what the state machine returns.
- Partial must NOT trigger the ladder - it logs a warning and continues to structuring.
