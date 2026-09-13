# Phase 7 - Pre-Shipping Review Problem Statements

**Status:** awaiting implementation in a fresh session
**Created:** 2026-09-13 (two-axis code review of the whole Phase 7 diff)
**Owner decisions locked:** see "Decisions already made" below.

## Session context (for whoever picks this up)

- Repo: `D:\Dev\Projects\CareSetu`, branch `feat/phase-7-intake-schema` (HEAD `08b07fb`).
- Differencing base (the "last PR"): `origin/main` = `ae0352c`. Every finding below exists within `git diff ae0352c...HEAD` (51 commits, 168 files, +26801/-79).
- Originating spec: GitHub issue **#344** (Phase 7 Symptom Intake + AI Pre-Summary, MOD-005). Binding rules cited below come from #344, `ADR-0001`, `ADR-0002`, roadmap `§2.7`, and `docs/standards/*`.
- Verify work with the repo harness before declaring done: `npm run test:unit:backend`, `npm run lint`, `npm run typecheck`, `npm run migration-check`, `npm run scan`.

## Decisions already made (do not re-open)

1. **AI budget = observe and warn only, no hard stop.** Cost must be _recorded for real_ (it is currently hardcoded to 0). Cost is computed from provider usage via a simple price calculation. Free models price at 0 naturally; paid models get a price-table entry later. Notification/dashboard UI is Phase 14 (operator dashboard) - nothing is wired now, only the data and a simple read path.
2. **No patient demographics (real or fake) in AI egress.** Delete the fabricated placeholders entirely. Doctors see patient identity only in their own UI.
3. **Voice/ASR path is kept for a later phase** (doctor consultation summary STT). Phase 7 keeps the seam but makes it safe to enable: consent + audit + metering on the transcribe leg.
4. **Re-recorded intake re-runs the AI path** (option (a)) - the `intake.retry_requested` no-op handler must be implemented to re-trigger the pipeline, not left as a drain.

## MUST FIX before push / deploy

### PS-01 - AI cost is never recorded, so the budget meter reports nothing real

- **Where:** `apps/backend/modules/intake/adapters/pipeline.py:591-593` - `_finalize_pipeline` hardcodes `token_input = 0`, `token_output = 0`, `cost_paise = 0` before writing the completed `ai_jobs` row. The OpenAI-compatible adapter already extracts real usage (`ai_provider_openai_compatible.py`, `_extract_usage_tokens` / `_extract_transcription_usage_tokens`) but only logs it.
- **Why it matters:** `budget_meter.py` sums `cost_paise` over `intake_ai_jobs` for the month (Postgres-first, standard B1). With cost always 0 there is no signal for any dashboard or warning, now or in Phase 14.
- **Expected fix:** extract real `input_tokens` / `output_tokens` from the provider's usage and write them into the completed job row. Compute `cost_paise` with a small helper: `input_tokens * price(in) + output_tokens * price(out)`, backed by a small per-model price table. Free models have price entries of 0 so their cost records 0 naturally; comment the table so adding a paid model later is one entry. No special-casing for "free" models.
- **Acceptance:** a completed `structure` job row (and a completed `transcribe` row, see PS-03) carries real tokens/cost/provider/model. No literal zeroing of metered fields in the write path.

### PS-02 - Fabricated patient demographics are sent to the AI egress

- **Where:** `apps/backend/modules/intake/adapters/__init__.py:64-65` defines `DEFAULT_EGRESS_AGE_RANGE = "30-40"` and `DEFAULT_EGRESS_SEX = "other"`; `pipeline.py:87-98` (`_egress_context`) injects them into `AiEgressContext` (defined in `ai_gateway.py`).
- **Why it matters:** spec #344 says egress carries "transcript (or text), declared language, age range, and sex." Hardcoded "30-40" / "other" for every patient is fabricated data; it misleads the LLM's structuring and any doctor reading the outcome.
- **Expected fix:** delete both constants; remove `age_range` / `sex` from `AiEgressContext` and all construction sites; ensure no egress payload carries patient identity fields. Add a guardrail test asserting the egress context carries only transcript/text + language (and the audio clip on the ASR leg).

### PS-03 - The voice/ASR egress is not audited or metered (must be safe before it is kept for later)

- **Where:** `pipeline.py:277-286` calls `gateway.transcribe(...)`. The consent gate (`check_consent`, line 213) and budget gate (line 201) sit in front of it, but `record_egress_disclosure` + `ai_egress.recorded` fire only for the structure leg (lines 426-439). A successful transcribe creates no `ai_jobs` row at all; only failures do (lines 288-295).
- **Why it matters:** spec #344 requires every egress to be consent-gated, PHI-minimized, audited, and metered. The transcribe seam stays for a later phase, so flipping a config must never create an unlogged egress.
- **Expected fix:** a successful transcribe call writes an `ai_jobs` row (task_type `transcribe`, real provider/model/tokens/cost/duration) and records an egress disclosure + publishes `ai_egress.recorded`, all in the same transaction. The mock path (no real egress) is unchanged.

### PS-04 - Pre-summary schema allows a phantom fourth state that nothing uses (verified dead)

- **Where:** migration `6cb15f638bec_v7_0__init_intake.py:95` and `schema/models.py:128` - CHECK constraint `review_state IN ('draft','review_required','reviewed','final')`; stale comments at `models.py:108,110` ("...forces review_required", "draft -> review_required | reviewed -> final"); a test pins the value at `tests/unit/test_intake_schema.py:85`.
- **Verification already performed:** the binding machine is three states (`domain/presummary_machine.py`: `Draft -> Reviewed -> Final`, "never a fourth" per `docs/agents/briefs/PHASE-7-T02-domain-state-machines.md`); roadmap `§2.7` lists `review_state Draft/Reviewed/Final` (`implementation-roadmap.md:511`); `low_confidence` is a derived property, not a state. Repo-wide grep shows `review_required` only in the migration, the model, and that test. **Not referenced by Phase 8 (`request_rx_draft`) or any later phase** - Phase 8 consumes a pre-summary ref under the ADR-0001 forced-review rule, which uses the real `reviewed` state.
- **Expected fix:** a corrective alembic migration relaxes the CHECK to exactly `('draft','reviewed','final')` (new revision - the live DB was already migrated under #373, so do not rewrite v7.0 alone); correct the stale model comments; update `test_intake_schema.py` to assert three states, not four. Run `npm run migration-check` after (single-head + cross-schema-FK gate).

### PS-05 - New intake routes are not rate limited

- **Where:** `app/main.py:254` - `RateLimitMiddleware` is scoped to the OTP/auth surface; the new `/v1/intake/*` routes (`adapters/routes.py`, upload-media + submit) have no limit.
- **Why it matters:** `api-standards` §6 names intake among the strictest-limit endpoints; upload + submit are spam/abuse surface that stores media and rows.
- **Expected fix:** intake upload and submit sit under the rate-limit tiers the standards specify for intake, with tests asserting the 429 envelope for the intake routes.

### PS-06 - Dead `Ext002AiProvider` class ships in the diff

- **Where:** `ai_provider_ext.py:74` - the class is never constructed: `build_ai_gateway` (line 290+) only builds `mock` or `openai_compatible` (whitelist validated in `app/config.py:303-307`), and the class is re-exported in `__all__` (lines 351-352) and `adapters/__init__.py:35`.
- **Note (already resolved with owner):** this is NOT the fallback chain or the .env provider list - `FallbackAiGateway` and the secondary OpenAI-compatible adapters are wired and correct. This is a legacy EXT-002 proxy whose `transcribe` still sends `audio_ref` (the pre-#392 seam), unreachable by any config value.
- **Expected fix:** remove the class (keep `build_ai_gateway`, `CircuitBreakerAiGateway`, `Ext002CallError`), update exports, and ensure no symbol reference remains. Future providers continue to arrive as `openai_compatible` config entries.

### PS-07 - A re-recorded intake can stall in `structuring` with no pipeline run (owner chose: re-run the AI path)

- **Where:** `adapters/__init__.py:180-192` - `_on_intake_retry_requested` registers a consumer whose `_impl` is `del connection, payload` (a no-op). The pipeline only runs from `_on_intake_captured` (line 158). `facade.re_record_intake` (`facade.py:296-400`) moves the intake to `structuring` and emits only `intake.retry_requested`. `coding-standards` §8 forbids bare no-op bodies.
- **Why it matters:** after the patient submits a re-recorded clip, the intake sits in `structuring` (implying an AI job is running) while nothing re-triggers the AI path.
- **Decision (owner):** option (a) - re-run the AI path. The `intake.retry_requested` handler must re-trigger the structuring pipeline for the re-recorded intake (or the re-record flow must re-emit `intake.captured`), so a retry moves into a real structuring pass like a first take.
- **Acceptance:** a re-recorded intake transitions to `structuring` and an AI job runs on the new capture (dedupe still applies); the no-op is gone. State-machine and facade tests (`test_presummary_state_machine.py`, intake facade/route tests) updated to cover re-record -> structuring -> pipeline re-run.

## Cleanup (owner asked to fix all)

### PS-08 - Frontend mirrors backend thresholds

- **Where:** `apps/frontend/src/lib/intake/voice.ts:9-25` re-declares `MAX_RECORD_MS`, `MIN_RECORD_MS`, `MAX_RECORD_ATTEMPTS`, `MAX_UPLOAD_ATTEMPTS`, backoff base, with a comment admitting they mirror the backend. `coding-standards` §9.2 forbids value duplication across languages.
- **Expected fix:** a parity unit test asserts the JS constants equal the Python constants (backend is source of truth), so drift is caught instead of silently diverging.

### PS-09 - Retry/backoff/error-typing loop copy-pasted across two adapters

- **Where:** `ai_provider_ext.py` `_post_json` (~99-158) vs `ai_provider_openai_compatible.py` `_post` (~167-239); only `_backoff_delay` is shared (in `ai_gateway.py`). The openai-compatible docstring claims the discipline is "reused from the existing Ext002AiProvider plumbing" but only the delay is shared.
- **Expected fix:** one shared post-with-backoff helper (respecting the ≤30 s timeout, exactly-3-retries, typed `Ext002CallError` split) used by both adapters; no duplicated loop remains.

## Budget observe-and-warn (PS-10, folded design)

**Prerequisite:** PS-01 (the meter is only meaningful once real cost lands in `ai_jobs`).

1. Keep `budget_meter.py`'s authoritative SQL read path intact - it is the Phase 14 cost-dashboard data source (`docs/plans/plan-post-phase14-observability.md` already owns cost telemetry and the nightly cost rollup).
2. Default behavior: **never block an AI call on spend.** The `allows_ai_call` gate consulted at `pipeline.py:201` becomes advisory - the pipeline always proceeds; the meter only reports.
3. No alert, no hook, no notification wiring now. Real cost in `ai_jobs` is the signal; Phase 14 builds its dashboard/alert off that SQL aggregate.
4. Keep the budget `Settings` knob (`ai_monthly_budget_paise`) so a cap can be reintroduced later without a rewrite.
5. Record the deviation from spec #344 ("hard stop: budget exhausted => no new AI calls") and PRD NFR-001 in the roadmap decision-note area and the budget-meter docstring; update the budget-meter tests that currently assert the hard-stop gate.
