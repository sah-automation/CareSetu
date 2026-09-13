# Brief - 399 T02 Pricing helper + real cost in completed jobs

**Ticket:** #399 · **Parent:** #397 · **Refreshed:** 2026-09-13
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

A per-model pricing helper computes `cost_paise = input_tokens * price_in + output_tokens * price_out`; free models carry 0 entries, an unknown model costs 0 with a comment that a paid model must carry an entry. `_finalize_pipeline` writes real tokens and cost into the completed `ai_jobs` row, deleting the hardcoded zeroing block. Acceptances: helper returns paise per the formula from a per-model table; a completed structure job row carries real provider/model/tokens/cost; no zero literals remain in the write path.

## Read-list (in order)

1. `modules/intake/budget_meter.py` - the cost signal this feeds (`COALESCE(SUM(cost_paise),0)` over `intake_ai_jobs`); place the new pricing helper module beside it (~1.5K)
2. `modules/intake/adapters/pipeline.py` - `_insert_ai_job` (:463-492) and `_finalize_pipeline` (:564-609, the zero-literal block ~:591-605); wire real tokens/cost into the completed-row write (~2K)
3. The token fields landed by #398 on the result DTOs - the values `_finalize_pipeline` reads off `StructureResult` (~0.3K)

## Do NOT read

- Provider adapter internals (`_post`, usage extraction) - #398 owns those
- Transcribe-leg job writing - that is #401's edit
- `budget_meter.py` gating logic (`allows_ai_call`) - #408 makes it advisory
- Frontend sources, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1732 passed (verified 2026-09-13)
- `npm run typecheck:backend` - mypy strict clean
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - new pricing-helper tests + consumer-harness test asserting the completed structure job row carries real provider/model/input_tokens/output_tokens/cost_paise (prior art `test_intake_pipeline_consumer.py`)
- `npm run typecheck:backend` clean

## Handoff notes

- Blocked by #398; gate your finalize-write on the result carrying token fields from #398
- `intake_ai_jobs` already has `input_tokens`/`output_tokens`/`cost_paise` nullable columns - no migration needed
- Payment math precedent lives in `phase0/harness/` (Whisper/Gemini pricing) as historical reference only; the app gets a new minimal helper
