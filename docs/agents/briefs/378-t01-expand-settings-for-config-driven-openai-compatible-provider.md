# Brief - 378 AI Gateway T01: Expand settings for config-driven openai_compatible provider

**Ticket:** #378 · **Parent:** #377 · **Refreshed:** 2026-09-11
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Extend the shared `Settings` config with the config-driven AI provider contract: whitelist changes to `{"mock", "openai_compatible"}`, new `AI_MODEL` required setting, dev override `AI_ALLOW_DEV_PROVIDER`, and the all-or-none fallback set. Keep mock default and `demo_mode` fail-closed behavior. No adapter or pipeline changes - this ticket only shapes the config surface and its validation.

Acceptance criteria (from #378):

- [ ] `AI_PROVIDER` whitelist changes from `{"mock", "provider"}` to `{"mock", "openai_compatible"}`
- [ ] `AI_MODEL` is a new required setting (non-empty when `openai_compatible`)
- [ ] `AI_ALLOW_DEV_PROVIDER` boolean setting overrides the staging/production gate for dev/test
- [ ] Fallback settings added: `AI_FALLBACK_PROVIDER`, `AI_FALLBACK_BASE_URL`, `AI_FALLBACK_API_KEY`, `AI_FALLBACK_MODEL`
- [ ] Fallback all-or-none: if any fallback var is set, all four must be set; only `openai_compatible` accepted as fallback provider
- [ ] `demo_mode=True` still forces `mock` unconditionally
- [ ] `openai_compatible` requires non-empty `AI_API_KEY`, `AI_BASE_URL`, `AI_MODEL`
- [ ] Existing validation (timeout, retries, breaker, budget) unchanged
- [ ] All acceptance criteria verifiable via unit tests

## Read-list (in order)

1. `Settings` dataclass + `__post_init__` in `apps/backend/app/config.py` - the provider whitelist check (lines ~269-302), the `ai_*` fields (~194-201), and the `get_settings()` env resolution (~475-489). Model your new fields/validation on the existing `sms_provider`/`whatsapp_provider` gating blocks (~2.5K tokens)
2. Defaults block in `config.py` (~90-98) - where `DEFAULT_AI_*` constants live; add `DEFAULT_AI_MODEL` etc. alongside (~300 tokens)
3. Existing settings-validation tests in `tests/unit/test_ai_gateway_mock.py` - `test_build_ai_gateway_provider_path`, `test_ai_provider_key_refused_in_dev_test_without_demo`, `test_ai_provider_production_requires_key`, `test_ai_provider_production_requires_base_url`, `test_demo_mode_forces_mock`, `test_unsupported_ai_provider_is_refused`, `test_ai_timeout_must_honour_ext002_discipline` (~2K tokens)
4. `docs/standards/coding-standards.md` - config is behavior, `__post_init__` patterns (~1K tokens)

## Do NOT read

- `ai_gateway.py`, `ai_provider_ext.py`, `ai_provider_mock.py`, `pipeline.py` - those are tickets T02-T04; the adapter/pipeline don't change here
- `.env` (it contains a real key scratchpad and an intentionally invalid `AI_PROVIDER="Google"` value; not a spec)
- Frontend code, integration/e2e test harnesses

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - NOTE: currently has pre-existing failures/errors (6 failed, 46 errors: `test_app_shell` OTP-gating, `test_migration_fk_checker`, `test_phase0_cost`, `test_seed_demo`). These are environment-dependent (need local DB / env) and unrelated to AI config. Run the AI-gateway subset to confirm THOSE are green: `pytest tests/unit/test_ai_gateway_mock.py`
- `npm run typecheck` - currently fails with ENOSPC (no space on C:). D: has 327 GB free; set npm cache/temp to D: or free C: space before running. The AI-gateway module files should typecheck clean with only the config.py changes

## Done-verify (acceptance criteria -> commands)

- `pytest tests/unit/test_ai_gateway_mock.py -q` passes (existing + new settings tests)
- New tests cover: unknown provider refused, `openai_compatible` accepted, dev gate refuses without override, override permits dev use, `demo_mode` forces mock, fallback all-or-none (partial sets refused), missing key/base/model refunds, fallback provider value whitelist
- `python -m mypy apps/backend --strict` (or `npm run typecheck`) clean once disk space resolved

## Handoff notes

- The old `{"mock", "provider"}` value and its `ai_provider="provider"` gating block are replaced - remove `provider` from the whitelist and the SMS-style staging/production gating that referenced it; the new provider name is `openai_compatible`
- The `.env` scratchpad declares `AI_PROVIDER="Google"` which will now refuse to boot (expected) - do not "fix" `.env`, it is gitignored provisioning scratch that `Settings` never loads
- Keep `AI_TIMEOUT_SECONDS`, `AI_MAX_RETRIES`, `AI_CIRCUIT_BREAKER_*`, `AI_MONTHLY_BUDGET_PAISE` validation untouched (they are shared by every provider)
- The fallback provider whitelist accepts only `openai_compatible` (per issue #377 Implementation Decisions)
- This ticket is blocked by nothing; it unblocks T02 (#379)
