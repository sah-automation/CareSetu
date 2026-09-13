# Brief - 404 T07 Remove legacy Ext002AiProvider adapter

**Ticket:** #404 · **Parent:** #397 · **Refreshed:** 2026-09-13
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

The unreachable legacy provider is removed. `Ext002AiProvider` is deleted - never constructed by any config value (`build_ai_gateway` only builds mock/openai_compatible per the `app/config.py:303-307` whitelist) and its transcribe still sends the pre-#392 `audio_ref` seam. The config-driven builder, circuit breaker, and typed call error STAY. Exports and all symbol references are removed; test harnesses that constructed it migrate to the OpenAI-compatible adapter or to minimal in-file failing fakes. Acceptances: the class + its exports/re-exports are gone; the builder, breaker, and typed error remain; no symbol reference remains (grep-clean) and the migrated tests pass.

## Read-list (in order)

1. `modules/intake/adapters/ai_provider_ext.py` - the dead class (:74) vs. what STAYS: `build_ai_gateway` (:290-346), `CircuitBreakerAiGateway` (:201), `Ext002CallError` (lives in `ai_gateway.py:152`), `__all__` (:351) (~4K)
2. `modules/intake/adapters/__init__.py` - the re-export to drop (~0.5K)
3. Tests that construct the legacy class and must migrate: `tests/unit/test_ai_gateway_mock.py`, `tests/unit/test_ai_gateway_fallback.py`, `tests/integration/test_intake_closed_loop.py` (:53, :302) - move coverage onto the OpenAI-compatible adapter or in-file fakes (~2.5K)

## Do NOT read

- The OpenAI-compatible adapter's `_post` retry internals - the shared-helper extraction is #405's edit (after this ticket removes the second loop)
- `pipeline.py`, `budget_meter.py`, frontend, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1732 passed (verified 2026-09-13)
- `npm run typecheck:backend` - mypy strict clean
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- Grep-clean: `Ext002AiProvider` appears nowhere in source, exports, or tests
- `npm run test:unit:backend` - gateway adapter + closed-loop test files pass on the migrated harnesses

## Handoff notes

- This is NOT the fallback chain or the .env provider list - `FallbackAiGateway` and secondary openai-compatible adapters stay
- Do not touch `_post_json`'s retry logic while deleting the class unless the migration forces it; #405 extracts the shared retry helper right after
- The closed-loop references (#409's file) are migrated here, so #409 must land after this ticket
