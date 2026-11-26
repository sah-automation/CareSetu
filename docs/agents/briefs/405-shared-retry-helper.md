# Brief - 405 T08 Shared post-with-backoff retry helper

**Ticket:** #405 · **Parent:** #397 · **Refreshed:** 2026-09-13
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

The retry/backoff/call-error loop is written once. One shared post-with-backoff helper replaces the remaining loop after #404: supports JSON and multipart call shapes, keeps the ≤30 s client timeout, exactly-3-retries, and the typed outage-vs-contract error split (`Ext002CallError`), and carries the retry discipline import used by all real provider adapters going forward. The OpenAI-compatible adapter delegates to it; no duplicated loop remains. Acceptances: a single shared helper implements the discipline; the OpenAI-compatible adapter delegates, both JSON and multipart shapes supported; no duplicated loop remains; retry/timeout/error-typing tests pass.

## Read-list (in order)

1. `modules/intake/adapters/ai_provider_openai_compatible.py` - `_post` (:167-239) and its callers (`transcribe` multipart, `structure` JSON) (~3K)
2. `modules/intake/adapters/ai_gateway.py` - `_backoff_delay` (:40), `Ext002CallError` (:152) - the shared house the helper should live in (~0.5K)
3. `app/config.py` - `DEFAULT_AI_TIMEOUT_SECONDS` = 30.0 (:104), `DEFAULT_AI_MAX_RETRIES` = 3 (:105) and their validation (:358-364) (~0.5K)
4. Tests `test_ai_gateway_openai_compatible.py`, `test_ai_gateway_fallback.py` - the behavior that must keep passing (~1K, skim)

## Do NOT read

- `pipeline.py`, `budget_meter.py`, frontend sources, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1732 passed (verified 2026-09-13)
- `npm run typecheck:backend` - mypy strict clean
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - retry/timeout/error-typing tests (prior art `test_ai_gateway_openai_compatible.py`) pass against the shared helper
- `npm run typecheck:backend` clean

## Handoff notes

- Blocked by #404 (which deletes the `_post_json` loop in the ext class); after it there is one loop left to extract
- Keep the named split: network/timeout + 429/5xx retryable, 4xx non-retryable, malformed/non-JSON payload non-retryable, exhausted -> `Ext002CallError(retries_exhausted=True)`
- `UPLOAD_RETRY_BASE_MS`/`uploadBackoffDelayMs` on the frontend are unrelated - those belong to #407
