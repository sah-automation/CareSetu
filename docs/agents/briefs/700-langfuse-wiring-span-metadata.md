# Brief - 700 B2 - Wire Langfuse singleton + span metadata + PHI-free test

**Ticket:** #700 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Wire the existing Langfuse singleton explicitly at app and worker boot (rather than relying on the SDK's env-global client), and enrich the `@observe` AI spans with the documented metadata set: task type, provider, model, input/output tokens, duration, cost (paise), confidence, status, pseudonymous ids, trace id, and prompt version. Add a unit test asserting the span metadata admits only allow-listed keys, so no transcript text, patient identity, or raw provider payload can be attached. Keys absent = behaviour unchanged.

### Acceptance criteria

- [ ] `get_langfuse_client` is called at both composition roots; when keys are absent boot is unchanged.
- [ ] AI spans carry the allow-listed metadata only; enrichment never raises into the AI call path.
- [ ] A unit test asserts the metadata allow-list - a non-allow-listed key is rejected.
- [ ] `npm run typecheck`; `npm run test:unit:backend` pass; the AI-tracing gate still passes.

## Read-list (in order)

1. `observability.langfuse_client.get_langfuse_client` and `observability/__init__` - the singleton signature `(public_key, secret_key, host)`, lazy once-per-process init, and the `None` return when `public_key` is blank (the SDK is not even imported). This is the explicit-wiring target. (~0.6K tokens)
2. The parent plan's §6 "Span metadata" list - the exact allow-list: `task_type`, `provider`, `model`, `input_tokens`, `output_tokens`, `duration_ms`, `cost_paise`, `confidence`, `status`, pseudonymous `intake_id`/`ai_job_id`, `trace_id`, prompt version; and the never-list (transcript text, patient identity, raw provider payloads). (~0.5K tokens)
3. The MOD-005 AI adapters carrying `@observe` - `ai_provider_ext.CircuitBreakerAiGateway`, `ai_provider_fallback.FallbackAiGateway`, `ai_provider_mock`, `ai_provider_openai_compatible` (the `transcribe` / `structure` / `draft_rx` decorated methods) - the enrichment sites; note `import langfuse.observe` is imported directly from the SDK, not through the `observability` package. (~2K tokens)
4. `scripts.check_ai_tracing` and `tests.unit.test_check_ai_tracing` - the A7 gate's rule (an AI-boundary method must reference `@observe` or the langfuse client) and the fixture-test shape the new allow-list test sits beside. (~2.5K tokens)
5. The two composition roots: `app.main.create_app` lifespan and `worker.main.run_worker_until_stopped` - where an explicit `get_langfuse_client(...)` call must be added (with shutdown flush if buffered). (~1K tokens)
6. `app.config.Settings` Langfuse fields - `langfuse_public_key`, `langfuse_secret_key`, `langfuse_host` and the `__post_init__` all-or-none key-pair guard. (~0.4K tokens)

## Do NOT read

- MOD-013 / the `observability` schema (B3, not built yet).
- The frontend.
- Migrations (B2 is migration-free).

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS (current tree)
- `npm run test:unit:backend` - PASS (2925 passed)
- The AI-tracing gate (`scripts/check_ai_tracing.py` via pre-commit/CI)

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck`
- `npm run test:unit:backend`
- `tests/unit/test_check_ai_tracing.py` still passes (A7 gate clean on the real tree).
- New unit test: metadata spanning a documented key passes; a non-allow-listed key (e.g. transcript or patient name) is rejected.

## Handoff notes

- Put the allow-list in one small helper in the `observability/` package (e.g. a span-metadata builder/validator) and have the adapters call it, so the PHI-free contract is testable at one seam and cannot drift per adapter.
- Enrichment is best-effort: wrap it so a Langfuse/network error never raises into the AI call path. Absent keys must leave `@observe`'s current behaviour untouched.
- Pseudonymous ids only - `intake_id` / `ai_job_id`, never phone, name, or transcript. The A7 gate test (`test_check_ai_tracing.py`) is the closest prior art for a "gate stays green" assertion.
- Wiring the singleton explicitly at boot must remain a no-op when both Langfuse keys are blank (the `Settings.__post_init__` already refuses a partial key pair).
