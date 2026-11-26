# Brief - 398 T01 Metering seam: usage tokens on AI gateway results

**Ticket:** #398 · **Parent:** #397 · **Refreshed:** 2026-09-13
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

The AI gateway result models gain optional input/output token counts defaulting to 0. The OpenAI-compatible adapter populates them from the provider usage it already extracts (currently logs then discards); mock and fallback adapters report real 0. Acceptances: the three result models carry optional token fields defaulting to 0; the OpenAI-compatible adapter populates them on the structure and transcribe legs (incl. the Groq `x_groq.usage` shape); mock/fallback set real 0; adapter-boundary tests assert the token counts. This is PS-01's first half and the prerequisite for #399 and #401.

## Read-list (in order)

1. `modules/intake/adapters/ai_gateway.py` - the `AiGateway` protocol + `TranscribeResult` (:88), `StructureResult` (:106), `DraftRxResult` (:145) DTOs; add optional `input_tokens`/`output_tokens` int fields (default 0) to each result (~1.5K)
2. `modules/intake/adapters/ai_provider_openai_compatible.py` - `_extract_usage_tokens`, `_parse_usage`, `_extract_transcription_usage_tokens` (:296-325, the extraction already exists) and `transcribe`/`structure` (:368-407) which currently only `logger.info` the numbers; route them onto the results (~3K)
3. `modules/intake/adapters/ai_provider_mock.py` - `MockAiProvider` results; set real 0 usage fields (~0.5K)
4. `modules/intake/adapters/ai_provider_fallback.py` - `FallbackAiGateway` result pass-through; 0 usage fields (~1K)

## Do NOT read

- `pipeline.py` write paths (`_finalize_pipeline`/`_insert_ai_job`) - that is #399's edit, not yours
- `budget_meter.py`, `media_store.py`, `routes.py`, `facade.py`
- Frontend sources, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1732 passed (verified 2026-09-13)
- `npm run typecheck:backend` - mypy strict clean
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - `test_ai_gateway_openai_compatible.py`, `test_ai_gateway_mock.py`, `test_ai_gateway_fallback.py` assert token fields on results
- `npm run typecheck:backend` clean

## Handoff notes

- Prior art: `docs/agents/briefs/379-t02-openai-compatible-adapter-structure-leg.md` / `380-t03-fallback-chain-gateway.md` / `381-t04-wire-builder-pipeline-bookkeeping-and-env-documentation.md`
- #399 (real cost write) consumes these fields; keep the field names `input_tokens`/`output_tokens` so the job-write maps onto `intake_ai_jobs` columns that already exist
- Do not change the egress context in `ai_gateway.py` here - #400 owns `AiEgressContext`
