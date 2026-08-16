# Brief - 127 TEST-A1 - CI regression load test (k6 patient flow)

**Ticket:** #127 · **Parent:** #126 (TEST-SUITE) · **Refreshed:** 2026-08-15
**Reading surface:** ~3.5K tokens (budget 10K) - within budget

## Scope

A deterministic CI regression load gate: `npm run test:load` runs a k6 scenario driving the full patient flow - `register` -> `GET /v1/auth/dev/otp` -> `verify` -> `POST /v1/auth/session` -> `GET /v1/me` - against a locally-booted backend with throwaway Postgres, mock SMS, and `GATEWAY_RATE_LIMIT_ENABLED=false` (the same posture `playwright.config.ts` uses, so the auth surface is not capped). Ramp 10 -> 50 VUs; the in-process mock SMS adapter means each VU reads its own OTP over the HTTP dev/otp read-back with its own phone.

Thresholds (CI-hardware regression bounds, NOT product SLAs - plan §3.A1): error rate < 1%, p95 < 800 ms, p99 < 1.5 s. k6 is not pre-installed on GitHub runners: `ci.yml` must install it (e.g. `grafana/k6-action` or a download step) before the scenario runs - same explicit-install treatment as ZAP's JRE step in TEST-B1.

Runs on PR + merge (+ nightly later via TEST-NIGHTLY, which reuses this job through the ci.yml gate).

Acceptance criteria (verbatim):

- `npm run test:load` runs a k6 patient-flow scenario against a local rate-limit-disabled instance and exits non-zero when a threshold is exceeded, zero when within bounds
- The scenario uses per-VU phones and reads each OTP over `/v1/auth/dev/otp` (no shared phone, no fixed OTP)
- `ci.yml` has a load job that installs k6, boots the local instance, runs the scenario, and passes on PR + merge
- Threshold values and the "regression bound, not SLA" framing are documented next to the scenario

## Read-list (in order)

1. Plan `docs/plans/test-suite-plan/production-test-suite-plan.md` §2 (rate limiter per-IP, CI vs prod hardware), §3.A1, §5 - the exact scenario, thresholds, posture (~0.7K).
2. `playwright.config.ts` + `scripts/e2e-backend.cjs` - the rate-limit-disabled `BACKEND_ENV` posture to copy and the boot path (alembic upgrade head, then uvicorn on :8000) (~0.6K).
3. `apps/backend/app/config.py` - the `gateway_rate_limit_enabled`, `mock_otp_readback_enabled`, `demo_mode` settings and env names the harness relies on (~0.4K).
4. `apps/backend/app/main.py` - the exact routes the scenario drives: `POST /v1/auth/register|verify|session`, `GET /v1/auth/dev/otp` (mock read-back), `GET /v1/me` (~0.5K).
5. `apps/backend/modules/iam/adapters/routes.py` + `facade.py` result models - the request/response bodies the k6 scenario must encode (`RegisterPatientResult`, `VerifyOtpResult`, `SessionResult`, `MeResponse`) (~0.7K).
6. `.github/workflows/ci.yml` - the e2e job's Postgres 16-alpine service block + `uv sync`/`npm ci` + `uv run --directory apps/backend` patterns to reuse for the new load job (~0.6K).
7. `tests/e2e/auth-loop.spec.ts` - the canonical patient-flow call sequence to mirror in the k6 scenario (~0.4K).

## Do NOT read

- The frontend source, `docs/archive/`, unrelated module specs, Lighthouse/axe/ZAP/SBOM sections of the plan.

## Baseline verify (must pass before the first edit)

- `npm run lint`, `npm run typecheck`, `npm run test:unit`, `npm run migration-check` (all green on 2026-08-15).

## Done-verify (acceptance criteria → commands)

- `npm run test:load` passes locally (k6 installed) with the threshold annotation visible in the scenario file
- Green ci.yml run on the PR with the load job passing

## Handoff notes

- k6 must be installed in the ci.yml job explicitly; the local `npm run test:load` needs a local k6 binary.
- The local backend venv launcher `scripts/py.cjs` hardcodes a Windows path - CI must use `uv run --directory apps/backend` like the e2e job, not the npm py.cjs scripts.
- The scenario must mint per-VU phones (e.g. `+91 9xxxxxxxxx` with a per-VU suffix) and read each OTP back over `/v1/auth/dev/otp?phone=...`; never share a phone or hardcode an OTP.
- This job is the boot harness TEST-B1 (#135) and TEST-A2 (#134) reuse - keep the local-instance boot (Postgres service + mock SMS + `GATEWAY_RATE_LIMIT_ENABLED=false`) as a clean, copyable step.
- Do not touch the auth rate limiter's default posture in `config.py`; the disabled flag is passed as env to the booted instance only.
