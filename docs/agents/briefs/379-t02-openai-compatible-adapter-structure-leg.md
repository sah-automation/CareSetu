# Brief - 379 AI Gateway T02: OpenAI-compatible adapter (structure leg)

**Ticket:** #379 · **Parent:** #377 · **Refreshed:** 2026-09-11
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Add a new `OpenAiCompatibleAdapter` implementing the `AiGateway` port against any standard chat-completions REST endpoint for the structure leg. `structure` returns a parsed `StructureResult`; `transcribe` and `draft_rx` raise the typed non-retryable error with "not supported in this phase". Prefactor: generalize `CircuitBreakerAiGateway` so it wraps any `AiGateway` (not only `Ext002AiProvider`).

Acceptance criteria (from #379):

- [ ] `CircuitBreakerAiGateway` generalized to accept any `AiGateway` instance (not only `Ext002AiProvider`)
- [ ] New `OpenAiCompatibleAdapter` implements `AiGateway` port: `structure`, `transcribe`, `draft_rx`
- [ ] Constructor takes `api_key`, `base_url`, `model`, injectable `timeout_seconds`/`max_retries`/`client`/`sleep`
- [ ] `structure` POSTs `{base_url}/chat/completions` with Bearer auth, `model`, messages (system = clinical structurer role, user = transcript + age_range/sex/language from `AiEgressContext`), JSON-mode response format
- [ ] First-choice content parsed into `StructureResult` via Pydantic; `usage.prompt_tokens`/`completion_tokens` extracted when present
- [ ] `transcribe` and `draft_rx` raise `Ext002CallError(retries_exhausted=False)` with "not supported in this phase" message
- [ ] Timeout <= 30 s and retry discipline (exponential + jitter, injectable sleep) reused from existing plumbing, not duplicated
- [ ] Outage failures (network/timeout/429/5xx after retries) typed `retries_exhausted=True`; contract rejections (4xx, malformed payload, schema validation failure) typed `retries_exhausted=False`
- [ ] `@observe` on all three methods (AI-tracing pre-commit gate stays green)
- [ ] Egress carries only `AiEgressContext` plus the transcript - never name, phone, or full record
- [ ] Unit tests via `httpx.MockTransport`: happy-path parse, token extraction, 429/5xx retry then outage, 4xx non-retryable, malformed payload non-retryable

## Read-list (in order)

1. `AiGateway` port + DTOs in `apps/backend/modules/intake/adapters/ai_gateway.py` - `StructureRequest`/`StructureResult`/`AiEgressContext` shapes, the protocol contract (all `extra="forbid"`) (~1.5K tokens)
2. `Ext002AiProvider` + `CircuitBreakerAiGateway` + `Ext002CallError` + `_backoff_delay` + `build_ai_gateway` in `apps/backend/modules/intake/adapters/ai_provider_ext.py` - the retry loop, error taxonomy, breaker, and wiring you model the new adapter on (~3.5K tokens)
3. `MockAiProvider` in `ai_provider_mock.py` - how a provider is `@observe`-decorated and DTO-validated (~1K tokens)
4. Provider test patterns in `tests/unit/test_ai_gateway_mock.py` - `test_provider_adapter_implements_all_three_operations`, wire-payload tests, breaker tests (~1.5K tokens)
5. `docs/standards/third-party-integration-standards.md` + `docs/standards/ai-engineering-standards.md` A2/A6/A7 - timeout/retry/JSON-mode/tracing rules (~0.5K tokens)

## Do NOT read

- `pipeline.py`, `__init__.py` (composition root) - T04 wires them; the adapter is standalone here
- `config.py` - only the `Settings` fields exist; T01 defined them, you just consume settings via `build_ai_gateway` in T04
- `test_notify_fallback.py` (T03 concern)
- Frontend, integration/e2e harnesses

## Baseline verify (must pass before the first edit)

- `pytest tests/unit/test_ai_gateway_mock.py -q` passes (AI-gateway subset; full `npm run test:unit:backend` has pre-existing environment failures unrelated to this work)
- `npm run typecheck` - currently blocked by ENOSPC (no space on C:); free C: space or redirect npm cache/temp to D: first. The adapter must be mypy --strict clean

## Done-verify (acceptance criteria -> commands)

- `pytest tests/unit/test_ai_gateway_mock.py -q` passes (existing + new adapter tests)
- New tests via `httpx.MockTransport`: happy-path `StructureResult` parse; usage token extraction when present; 429/5xx retry then `Ext002CallError(retries_exhausted=True)`; 4xx immediate `retries_exhausted=False`; malformed payload `retries_exhausted=False`; egress payload carries only intake context (never name/phone)
- `npm run check:ai-tracing` (or the pre-commit `check_ai_tracing` script) green over the new file
- `npm run typecheck` clean (once disk space resolved)

## Handoff notes

- The prompt is additive: system role = clinical structurer; user message = transcript + declared language/age_range/sex from `AiEgressContext`. Reuse the existing `DEFAULT_EGRESS_AGE_RANGE="30-40"` / `DEFAULT_EGRESS_SEX="other"` convention when building the user message unless a request context provides real values
- Reuse `Ext002CallError` and `_backoff_delay` from `ai_provider_ext.py` directly (import) rather than duplicating - the taxonomy is unchanged per issue #377
- Generalize `CircuitBreakerAiGateway.__init__` type hint from `Ext002AiProvider` to the `AiGateway` port; its runtime logic is already protocol-compatible (it only calls `transcribe`/`structure`/`draft_rx`)
- The mock is never wrapped in a breaker and stays the dev/test default (T04's concern, but keep that invariant)
- Keeping `@observe` on every public method is mandatory - `check_ai_tracing.py` AST-scans anything matching `gateway|provider` in `modules/intake/`
- The response format: request a JSON-mode response (`response_format={"type": "json_object"}` or equivalent), parse `choices[0].message.content` as JSON into the `StructureResult` schema; read `usage.prompt_tokens`/`usage.completion_tokens` when present
