# Brief - T14 Allow real AI provider under demo mode (AI_ALLOW_DEMO_PROVIDER opt-in flag)

**Ticket:** #414 · **Parent:** n/a · **Refreshed:** 2026-09-14
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

The deployed demo site serves mock/canned pre-summaries because (1) render.yaml blueprint hardcodes `AI_PROVIDER=mock` and `DEMO_MODE=true`, so every blueprint sync overwrites the dashboard's real provider, and (2) `Settings.__post_init__` fail-closed gate refuses a real AI provider while `demo_mode=True`. Introduce an explicit opt-in flag `AI_ALLOW_DEMO_PROVIDER` that relaxes the demo-AI gate so a real OpenAI-compatible provider can run under `DEMO_MODE=true` (demo OTP read-back login stays unchanged). Mirror the existing `AI_ALLOW_DEV_PROVIDER` pattern; dev/test gate, SMS/OTP gate, gateway builder, pipeline, and frontend are all untouched.

Acceptance criteria (from ticket user stories + testing decisions):

- New `ai_allow_demo_provider: bool = DEFAULT_AI_ALLOW_DEMO_PROVIDER` (default False) read from env `AI_ALLOW_DEMO_PROVIDER`
- Gate change: `if self.demo_mode and ai_provider != "mock" and not self.ai_allow_demo_provider: raise`; flag ignored when `demo_mode=False`; SMS/OTP and dev/test gates unchanged
- render.yaml: `AI_PROVIDER=openai_compatible`, `AI_ALLOW_DEMO_PROVIDER=true` blueprint-managed; `AI_API_KEY`/`AI_FALLBACK_API_KEY`/`AI_MODEL`/`AI_BASE_URL`/`AI_ASR_MODEL`/`AI_FALLBACK_*` dashboard-only (sync:false)
- `.env.example` and deployment plan sections 5.2 + 7 updated
- Unit tests: demo+openai_compatible without flag raises; with flag + valid keys boots; with flag + missing key raises; flag off in non-demo boots; demo+mock boots unflagged

## Read-list (in order)

1. `apps/backend/app/config.py` - `Settings` dataclass, the `demo_mode`/`ai_provider` gate in `__post_init__`, and `get_settings()` env wiring; the `AI_ALLOW_DEV_PROVIDER` flag is the pattern to mirror (~1.5K)
2. `tests/unit/test_ai_gateway_mock.py` - existing config-validation test patterns around lines 260-389 (dev-gate tests, `test_demo_mode_forces_mock`, `_staging_openai_settings` helper); new tests go beside them (~1K)
3. `render.yaml` - the AI env block (~0.5K) and `.env.example` AI quick-switch block (~0.5K)
4. `docs/plans/deployment-plan/portfolio-deployment-plan.md` §5.2 env-var table and §7 caveat table (~0.5K)

## Do NOT read

- `build_ai_gateway` / adapter internals (`ai_provider_ext.py`, `ai_provider_openai_compatible.py`) - gateway already resolves the real adapter; only the config gate blocks it
- The intake pipeline, any frontend code, `docs/archive/`, the `test_gateway.py` middleware suite (the ticket's "test_gateway.py" reference is a mislabel - AI config tests live in `test_ai_gateway_mock.py`)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1781 passed (verified 2026-09-14, after `git reset --hard origin/main` @ b8c8dea)
- `npm run typecheck` - clean (verified 2026-09-14)

## Done-verify (acceptance criteria to commands)

- `npm run test:unit:backend` (demo-config tests in `tests/unit/test_ai_gateway_mock.py`)
- `npm run typecheck`
- `npm run lint`
- `npm run migration-check`

## Handoff notes

- Local main was diverged from origin/main (older Langfuse-groundwork commit); sync with `git reset --hard origin/main` before starting.
- The ticket's user story 5 asks for AI_MODEL/AI_BASE_URL as committed blueprint values, but its Further Notes say only the toggles (AI_PROVIDER, DEMO_MODE) need the render.yaml edit. The operator confirmed all provider values are set in the Render dashboard with `.env.example` names, so render.yaml declares the model/base-url/keys as `sync: false` (dashboard-only) - a blueprint `value:` would overwrite the working dashboard config on the next sync.
- The pre-existing integration latency test `test_p95_latency_under_50ms` fails on this dev machine on a clean base (p95 ~156ms vs 50ms gate) - unrelated to this ticket, do not chase it.
- PR #413 (in-process dispatcher) is already merged to origin/main; this ticket builds on that deployed state. After the render.yaml push the Render service must re-sync blueprint env vars to apply the toggle flip.
