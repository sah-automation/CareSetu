# Brief - 393 Pipeline feeds decrypted clip to transcribe; media-read failure degrades

**Ticket:** #393 · **Parent:** #388 · **Refreshed:** 2026-09-12
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

The pipeline's transcribe leg reads and decrypts the latest media clip through the intake media store and passes the real bytes into the transcribe request, so a voice intake transcribes against a healthy ASR provider and produces a normal pre-summary like a text intake. When the media-store read fails (missing object, storage outage, ciphertext authentication failure), the failure is handled exactly like a transcribe failure: a failed `transcribe` AI job is booked with the failure reason and the intake degrades to raw doctor review - an infra error can never strand a captured intake. Pre-call structural skips (voice with no media ref) stay as-is.

Acceptance criteria:

- [ ] Voice transcribe selects and decrypts the latest clip via the intake media store and puts the bytes on the transcribe request (unit test: bytes flow store -> request)
- [ ] Media-store read failure books a failed `transcribe` AI job with the failure reason
- [ ] Media-store read failure degrades the intake to Ready for Review for raw doctor review (same treatment as a transcribe failure); the handler does not raise; no dead-letter
- [ ] Ciphertext authentication failure (tampered media) degrades identically
- [ ] Voice with no media ref stays a logged structural skip with no ai_job row
- [ ] Happy-path voice intake unchanged: ends with a single `structure` job and a recorded transcript
- [ ] Text intakes unaffected (transcribe never reached)

## Read-list (in order)

1. `apps/backend/modules/intake/adapters/pipeline.py` - `_run_structuring_pipeline` voice leg: egress-gate build, latest-media select (media ref rows ordered by record attempt), the transcribe call, the transcribe-only `try/except (Ext002CallError, ValidationError)` that calls `_fail_job` + `_degrade_to_raw_review`, `_insert_ai_job` (task_type parameter), `_failure_reason`, `_finalize_pipeline`, and the structure leg for the success-path bookkeeping it must not disturb (~4K)
2. `apps/backend/modules/intake/adapters/media_store.py` - the `IntakeMediaStore.read` contract (returns bytes), `_decrypt` (AES-256-GCM, `InvalidTag` on tampering), and the constructors the pipeline's store is built with; plus `apps/backend/modules/intake/facade.py` `get_intake_media` prior art as the classification reference for read/decrypt failures (`MediaTransferError` family) (~1.5K)
3. `tests/unit/test_intake_pipeline_degradation.py` - the fake-engine harness (fake connection, patched egress gate / `build_ai_gateway`, `MockAiProvider.transcribe` side effects) and the existing transcribe-degrade assertions to extend (failed job, `ai_job.failed` event, RAW_TEXT transition, no raise) (~2.5K)
4. `tests/unit/test_intake_pipeline_consumer.py` - the voice happy-path (single structure job + transcript recorded), voice-without-media-ref skip, and replay-idempotency tests that must stay green (~1K)
5. `apps/backend/modules/intake/intake_models.py` - the media-ref DTO shapes (`MediaFile`, `MediaRefView`, object-key semantics) the pipeline reads to select the clip (~0.4K)

## Do NOT read

- Adapter internals (mock/ext/fallback, `ai_provider_openai_compatible.py`) - the gateway is a seam here, bytes go on `TranscribeRequest`
- Frontend · `docs/archive`

## Baseline verify (must pass before the first edit, verified 2026-09-12)

- `npm run test:unit:backend` - 1723 passed, 3 pre-existing failures unrelated to intake (`test_app_shell.py::test_dev_otp_gated_outside_dev_test_environment`, `test_app_shell.py::test_mock_sms_adapter_stored_in_demo_mode_but_not_production_default`, `test_seed_demo.py::test_otp_surface_disabled_by_default`)
- `npm run typecheck` - backend mypy clean (213 files)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new media-read-degrade tests plus the pipeline degradation/consumer suites green
- `npm run typecheck` - backend clean

## Handoff notes

- Blocked by #392: consumes the `TranscribeRequest.audio_bytes` field it adds. Do not change the field; populate it.
- Media-read failure set to degrade identically to a transcribe failure: book `task_type="transcribe"` failed job with reason `_failure_reason(exc)` (type name, PHI-free), publish `ai_job.failed`, `RAW_TEXT` transition to Ready-for-Review, return without raising (no dead-letter).
- The transcribe leg is the only unwrapped LLM call - keep the media-read in the SAME degrade path (catch media/decrypt errors alongside the adapter's typed errors), not the structure leg's except.
- The success path must stay byte-for-byte: do NOT book a transcribe job on success; happy voice intake still ends with one `structure` job.
- Pre-call structural skip (voice with no media ref / empty object key) stays a logged skip with no ai_job row.
- The media store price of this ticket: `read` + `_decrypt` in the pipeline, mirroring how `get_intake_media` classifies missing/tampered/storage-outage failures.
