# Brief - 112 DEPLOY-1 - Backend honours DEMO_MODE + CORS_ALLOWED_ORIGINS

**Ticket:** #112 · **Parent:** plan doc `docs/plans/deployment-plan/portfolio-deployment-plan.md` · **Refreshed:** 2026-08-15
**Reading surface:** ~7.5K tokens (budget 10K) - within budget

## Scope

Make the backend deployable as a public demo: `Settings` gains `cors_allowed_origins` (comma-separated env `CORS_ALLOWED_ORIGINS`, empty default = no extra origins) and `demo_mode` (env `DEMO_MODE`, default false), with the fail-closed rule `demo_mode=True` requires `sms_provider=mock`. `create_app` then: adds the env-configured Vercel origin to the CORS allow list while preserving and deduping the localhost dev origin; stores the mock SMS adapter on app state and answers `GET /v1/auth/dev/otp` when demo mode is on (gate becomes mock-provider AND (dev/test OR demo_mode)). With both flags off, behaviour is identical to today's production-default posture.

Acceptance criteria (verbatim):

- `Settings` parses `CORS_ALLOWED_ORIGINS` (comma-separated) and `DEMO_MODE` via helpers; defaults preserve today's posture
- `demo_mode=True` with `sms_provider=provider` raises at boot (fail-closed); mock provider passes
- `create_app` CORS `allow_origins` = dev localhost origin + configured origins, deduped; empty config adds nothing
- `GET /v1/auth/dev/otp` answers in demo mode (mock provider) exactly as in dev/test; returns 404 `DEV_OTP_UNAVAILABLE` otherwise
- Backend unit tests cover all of the above; `npm run test:unit:backend`, `npm run typecheck:backend` green

## Read-list (in order)

1. Plan `docs/plans/deployment-plan/portfolio-deployment-plan.md` §2.2 (gaps 1-2), §4.1, §4.3 - the exact fields, the fail-closed rule, the CORS composition, and the demo-OTP-gate change (~0.9K).
2. `Settings` dataclass (`apps/backend/app/config.py`) - the field/`__post_init__`/`_env_bool`/`_env_int`/`get_settings()` layout; add `cors_allowed_origins` + `demo_mode` and a `_env_csv` helper beside the existing `_env_*` helpers; extend `__post_init__` with the demo-mode validation; wire both into `get_settings()` (~1.7K).
3. `create_app` (`apps/backend/app/main.py`) - the CORS middleware block (`_DEV_CORS_ORIGINS`), the mock-sms-adapter storage gate, and the `dev_otp` route's current gate (~2.2K).
4. `tests/unit/test_app_shell.py` - the existing `dev_otp` + CORS tests and how they inject a resolved `Settings` into `create_app`; extend them for the two new flags (~2.5K).

## Do NOT read

- Alembic migrations, the dispatcher/outbox, `modules/iam/` internals beyond `adapters/sms.py` (build_sms_adapter), frontend sources, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (currently 570 passed)
- `npm run typecheck:backend` (currently clean)
- `npm run lint` (currently all pre-commit hooks pass)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new Settings + app-shell tests pass
- `npm run typecheck:backend`, `npm run lint` - clean

## Handoff notes

- The plan's §4.3 prose names only the route's gate, but the route reads the OTP off `app.state.mock_sms_adapter`, and `create_app` only stores that adapter when `sms_provider == "mock"` AND dev/test. Demo mode must ALSO store the adapter, or the route 404s even though the gate would allow it. Change both conditions.
- `_env_csv` splits on commas, strips whitespace, drops empties; empty/unset env gives `()` (no extra origins - the current production posture).
- `demo_mode=True` with `sms_provider=provider` raises in `__post_init__` (fail-closed: never let the demo flag ride a real provider).
- The existing tests build the app via `create_app(Settings(...))` with an injected dataclass - drive the new flags the same way rather than mutating the process environment.
- The 404 path keeps the existing `DEV_OTP_UNAVAILABLE` error envelope unchanged.
