# Brief - 386 Voice Intake T01: transcribe failure degrades to raw doctor review

**Ticket:** #386 · **Parent:** #384 · **Refreshed:** 2026-09-11
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

A voice intake captured against a real AI provider (the `openai_compatible` adapter) never stalls at `Captured` again. When `gateway.transcribe` raises the typed `Ext002CallError` (either the "transcribe not supported" contract rejection, `retries_exhausted=False`, or a genuine outage, `retries_exhausted=True`) or a `ValidationError`, the `intake.captured` handler books a failed `task_type="transcribe"` ai_job, publishes `ai_job.failed`, degrades the intake `Structuring -> Ready for Review` via the existing `RAW_TEXT` transition, and returns - all in the same transaction as the `consumed_events` ledger write. The licensed doctor reviews the raw transcript/audio, the outbox event is consumed exactly once, and replays are no-ops.

Acceptance criteria:

- [ ] When `gateway.transcribe` raises `Ext002CallError(retries_exhausted=False)` (the not-supported rejection) on a voice intake with a media ref: intake ends `Ready for Review`; an `intake_ai_jobs` row exists with `task_type="transcribe"`, `status="failed"`, `error_message="Ext002CallError"`; one `ai_job.failed` is published with `reason="Ext002CallError"`; no pre-summary content and no `task_type="structure"` job are produced; no `ai_job.completed`; and the handler does not raise
- [ ] The same outcome for `Ext002CallError(retries_exhausted=True)` (outage) - pinning the same degrade path for a future real-ASR outage
- [ ] A `ValidationError` raised from transcribe degrades identically (`reason="ValidationError"`)
- [ ] Replaying the same `intake.captured` `event_id` is a no-op (ledger already records it)
- [ ] Text intakes are unaffected - transcribe is never reached for text mode
- [ ] The success path is byte-for-byte unchanged: a successful voice intake still ends with a single `task_type="structure"` job; the mock provider still transcribes deterministically; unusable/partial re-record ladder and `forced_text` untouched
- [ ] Pre-call structural skips unchanged: voice with no media ref still degrades to a logged skip with no ai_job row

## Read-list (in order)

1. `apps/backend/modules/intake/adapters/pipeline.py` - `_run_structuring_pipeline` voice leg (~120–305: egress-gate build, consent/budget gates, media select, `gateway.transcribe` call, usability ladder), structure leg (~305–395: `_insert_ai_job` then try/except `(Ext002CallError, ValidationError)` that calls `_fail_job` + `_degrade_to_raw_review` and returns), then `_insert_ai_job` (~397–424, hardcodes `task_type="structure"`), `_failure_reason` (~427–429), `_degrade_to_raw_review` (~432–457, `RAW_TEXT` transition, never touches `forced_text`), `_fail_job` (~460–493, marks row failed + writes `ai_job.failed` envelope) (~4K)
2. `apps/backend/modules/intake/domain/events.py` - `AiTaskType` (line ~36), `AiJobFailedPayload` (`task_type`/`reason`, ~125–136), `ai_job_failed_envelope` (~237–248) - event contract the degrade path must publish (~0.5K)
3. `tests/unit/test_intake_pipeline_degradation.py` - structure-leg timeout and malformed-output tests (~260–318) plus the entire fake-engine harness (fake connection, `_run`, `_fake_egress_gate`) (~2K)
4. `tests/unit/test_intake_pipeline_consumer.py` - voice happy-path, text-mode-never-transcribes, and replay-no-op tests, same harness shape (~1K)
5. `apps/backend/modules/intake/adapters/ai_gateway.py` - `Ext002CallError` (~149–162, `retries_exhausted` semantics) and `AiGateway.transcribe` signature (~184) (~0.5K)

## Do NOT read

- `ai_provider_openai_compatible.py` internals (the real-ASR leg is ticket #387)
- `ai_provider_ext.py`, `ai_provider_fallback.py`, `ai_provider_mock.py`
- frontend sources, `docs/archive`, partner/iAM internals
- state-machine internals beyond the `RAW_TEXT` edge (`IntakeAction.RAW_TEXT`, `(STRUCTURING, RAW_TEXT) -> READY_FOR_REVIEW`)
- `bus/` internals beyond `handler_harness.run_handler`'s ledger-first contract (ledger write + handler effects in one transaction)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - warning: 3 pre-existing failures unrelated to intake (`test_app_shell.py::test_dev_otp_gated_outside_dev_test_environment`, `test_app_shell.py::test_mock_sms_adapter_stored_in_demo_mode_but_not_production_default`, `test_seed_demo.py::test_otp_surface_disabled_by_default`); all intake pipeline tests pass (verified 2026-09-11)
- `npm run typecheck` - clean (mypy + tsc, verified 2026-09-11)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new degrade tests (`test_intake_pipeline_degradation.py`) plus existing consumer/degradation suites green
- `npm run typecheck` - clean

## Handoff notes

- The transcribe leg is the ONLY unwrapped LLM call in `_run_structuring_pipeline`; the except currently at the structure leg (~338) must NOT catch transcribe errors - the transcribe failure handler is a separate `try/except (Ext002CallError, ValidationError)` around the transcribe call only.
- The transcribe failure books a job with `task_type="transcribe"` (schema and `AiTaskType` already admit it; no schema/state-machine change). Generalize `_insert_ai_job` with a `task_type` parameter defaulting to `"structure"` so the existing structure leg booking is unchanged.
- Book the failed job only in the failure path: a successful voice intake must STILL end with a single `task_type="structure"` job (byte-for-byte success path). Do not insert a transcribe job on success.
- The failure reason is `_failure_reason(exc)` = `type(exc).__name__` - PHI-free; `ai_job.failed` reason carries no clinical/identifying content.
- Pre-call structural skips (voice with no media ref / empty object key) stay logged skips with no ai_job row.
- Live verification caveat from the parent: a staging intake already stuck at `Captured` may have its `intake.captured` event dead-lettered after the attempts cap - verify with a freshly submitted voice intake, not the stale row.
- Docs text stating transcribe is "not supported in this phase" for the `openai_compatible` adapter is handled by ticket #387.
