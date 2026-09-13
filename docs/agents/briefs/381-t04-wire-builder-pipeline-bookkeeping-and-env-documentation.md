# Brief - 381 AI Gateway T04: Wire builder, pipeline bookkeeping, and env documentation

**Ticket:** #381 · **Parent:** #377 · **Refreshed:** 2026-09-11
**Reading surface:** ~10K tokens (budget 10K) - within budget

## Scope

Update `build_ai_gateway` to resolve mock or `openai_compatible` (with optional fallback chain) from config. Update the intake pipeline to record the effective provider + model on the `intake_ai_jobs` row (replacing the model placeholder). Update `.env.example` with the new config surface + quick-switch table. `render.yaml` stays on mock (fail-closed demo).

Acceptance criteria (from #381):

- [ ] `build_ai_gateway(settings)` resolves: `mock` -> mock adapter (unchanged, unwrapped); `openai_compatible` -> primary wrapped in circuit breaker; with fallback config present, wraps primary+secondary in `FallbackAiGateway`
- [ ] Dev override (`AI_ALLOW_DEV_PROVIDER`) wiring works end-to-end with configured settings
- [ ] `_insert_ai_job` accepts provider/model params (not hardcoded `MOCK_AI_MODEL`) and is updated for the structure task
- [ ] Pipeline reads the effective provider + model from the gateway after a successful structure call and records them on the AI job row (replacing the model placeholder)
- [ ] `_finalize_pipeline` writes the effective provider/model alongside confidence/tokens/duration
- [ ] Update `__init__.py` re-exports/constants (e.g. `MOCK_AI_MODEL` usage) to reflect the new bookkeeping
- [ ] Update `.env.example` with all new vars (`AI_MODEL`, `AI_ALLOW_DEV_PROVIDER`, `AI_FALLBACK_*`) and a quick-switch table (Groq, Google Gemini via OpenAI-compatible endpoint, OpenRouter, OpenAI)
- [ ] `render.yaml` keeps mock provider (fail-closed demo), only documents real-provider env surface
- [ ] Existing assertions that reference the model placeholder updated to the new bookkeeping contract
- [ ] Builder resolution unit tests: mock default, `openai_compatible` without fallback, `openai_compatible` with fallback, dev override

## Read-list (in order)

1. `build_ai_gateway` + `CircuitBreakerAiGateway` in `apps/backend/modules/intake/adapters/ai_provider_ext.py` - the resolver you extend; keep the mock branch unwrapped (~2.5K tokens)
2. `FallbackAiGateway` (from #380) and `OpenAiCompatibleAdapter` (from #379) - the types the builder composes (~2K tokens, skim since you wrote/own them this chain)
3. `_insert_ai_job` + `_finalize_pipeline` in `apps/backend/modules/intake/adapters/pipeline.py` (lines ~371-498) - where `MOCK_AI_MODEL` is hardcoded today and where the completed row is written; you thread the effective provider/model through here (~2K tokens)
4. `apps/backend/modules/intake/adapters/__init__.py` - `MOCK_AI_MODEL` constant + re-exports + `_on_intake_captured` -> pipeline wiring (~1.5K tokens)
5. `AiGateway` port surface for the effective provider/model accessor added in T03 (~0.5K tokens)
6. Tests to update: `tests/unit/test_ai_gateway_mock.py` (`test_build_ai_gateway_*` family) + `tests/unit/test_intake_pipeline_degradation.py` (assertions on the ai_jobs row) (~2K tokens)
7. `.env.example` + `render.yaml` - documentation targets (~0.5K tokens)

## Do NOT read

- `MockAiProvider` internals (unchanged), T02 adapter HTTP internals (only its constructor signature), T03 routing internals (only its effective-provider surface)
- Budget meter, consent gate, egress boundary, `budget_meter.py`, consent facade - untouched by this ticket
- Frontend, integration/e2e harnesses (the existing closed-loop integration keeps running against mock)

## Baseline verify (must pass before the first edit)

- `pytest tests/unit/test_ai_gateway_mock.py -q` and `pytest tests/unit/test_intake_pipeline_degradation.py -q` pass (full `npm run test:unit:backend` has pre-existing environment failures unrelated to this work)
- `npm run typecheck` - currently blocked by ENOSPC (no space on C:); free C: space or redirect npm cache/temp to D: first

## Done-verify (acceptance criteria -> commands)

- `pytest tests/unit/test_ai_gateway_mock.py -q` passes: `test_build_ai_gateway_default_is_mock`, mock knob, `openai_compatible`-without-fallback, `openai_compatible`-with-fallback, dev-override gate, plus updated assertions that no longer reference `"mock-model"`
- `pytest tests/unit/test_intake_pipeline_degradation.py -q` passes with the ai_jobs row carrying the effective provider/model
- `npm run check:ai-tracing` green
- `npm run typecheck` clean (once disk space resolved)
- `npm run lint` green

## Handoff notes

- The mock stays the fail-closed default and is NEVER wrapped in a breaker or fallback chain (per issue #377); the registry is keyed on `ai_provider` in `{"mock", "openai_compatible"}`
- The `intake_ai_jobs` provider/model columns already exist (v7.0 migration) - NO schema migration is required. On the completed row: provider = the serving provider type, model = the real model name sent (e.g. Groq `llama-3.3-70b-versatile`), replacing `MOCK_AI_MODEL` today
- `_insert_ai_job` runs BEFORE the gateway call (it bookmarks the running job). The effective provider/model is only known AFTER a successful structure call - so write the provider/model at `_finalize_pipeline` time (on the completed update), not at insert; the insert keeps the configured provider + placeholder model
- `demo_mode` still forces `mock` (config-level, T01) and `render.yaml`/deployment stays mock - confirm no prod env accidentally opts into a real provider
- The `.env` scratchpad's invalid `AI_PROVIDER="Google"` will refuse to boot under the new whitelist - expected; document via `.env.example` only, never edit `.env` (gitignored provisioning scratch)
- Effective provider/model accessor from T03 must be typed and cheap - the pipeline reads it once per successful call
