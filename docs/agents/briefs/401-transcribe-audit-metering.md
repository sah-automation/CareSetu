# Brief - 401 T04 Transcribe leg audit + metering

**Ticket:** #401 · **Parent:** #397 · **Refreshed:** 2026-09-13
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

A successful transcribe call writes an `ai_jobs` row (`task_type` `transcribe`) with real provider/model/tokens/cost/duration, records an egress disclosure, and publishes `ai_egress.recorded`, all in the same transaction as the ledger dedupe. The failure leg keeps its failed-row booking; the mock path (no real egress) is unchanged. A voice pass becomes two metered rows where both legs ran. Acceptances: successful transcribe writes the row with real values; transcribe leg records an egress disclosure and publishes `ai_egress.recorded` in the same transaction; transcribe failure still books its failed row and degrades to raw review as today.

## Read-list (in order)

1. `modules/intake/adapters/pipeline.py` - the transcribe leg (:277-311: success call at :279-286, failure booking at :288-301, degrade at :302-311); the structure-leg disclosure pattern to mirror (:426-444: `record_egress_disclosure` + `ai_egress_recorded_envelope`); `_insert_ai_job` (:463) and `_fail_job` (:528) (~4K)
2. `modules/intake/domain/events.py` - `ai_egress_recorded_envelope`, `AiEgressRecordedPayload` (:139-149, :251-260); `ai_job_completed`/`ai_job.failed` shapes (~1K)
3. `modules/consent/facade.py` - `record_egress_disclosure` (:644-677) signature + the AI egress constants from `modules/intake/adapters/__init__.py` (`AI_EGRESS_COUNTERPARTY_*`, `AI_EGRESS_RECORD_SCOPE`) (~1.5K)

## Do NOT read

- Pricing/token internals - #398/#399 land those; #401 consumes `result` token/cost already computed
- `budget_meter.py`, `media_store.py`, frontend sources, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1732 passed (verified 2026-09-13)
- `npm run typecheck:backend` - mypy strict clean
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - consumer-harness test (prior art `test_intake_pipeline_consumer.py`, `test_intake_pipeline_degradation.py`): two metered rows on a voice pass, egress row + `ai_egress.recorded` on transcribe success, failed-row booking preserved
- `npm run typecheck:backend` clean

## Handoff notes

- Blocked by #398 and #399; the job-row cost/duration fields come from those slices
- The `intake_ai_jobs.task_type` CHECK already admits `'transcribe'` - no schema change
- The disclosure/event must land in the SAME transaction as the ledger dedupe (the consumer harness runs handler + ledger write transactionally); the structure leg (:426-444) is the exact shape to replicate
