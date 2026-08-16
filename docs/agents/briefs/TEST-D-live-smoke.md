# Brief - 137 TEST-D - Post-deploy live smoke

**Ticket:** #137 · **Parent:** #126 (TEST-SUITE) · **Refreshed:** 2026-08-15
**Reading surface:** ~3.5K tokens (budget 10K) - within budget

## Scope

Automate the manual DEPLOY-7 verification as a hard-fail live smoke: `scripts/live_smoke.py`, run as a deploy.yml job after `deploy-render` and after Vercel's build settles. This is the crown-jewel gate - the demo itself must actually work on every merge.

The smoke performs, in order:

1. Warm-up request, then `GET /health` -> 200 `{"status":"ok"}`.
2. Full live demo flow with the Vercel `Origin` header on every call: register `+91 9000000001` -> `GET /v1/auth/dev/otp` -> verify -> `POST /v1/auth/session` -> `GET /v1/me` with Bearer (asserts `roles: ["patient"]`). Cooldown-aware: register on the seeded phone goes through the existing-phone login branch which honors the 60 s resend cooldown - if the smoke runs within 60 s of a prior OTP send, it must wait out the window and retry rather than fail (mirrors the e2e's cooldown catch).
3. Assert `access-control-allow-origin` echoes the Vercel origin on every response (guards the CORS regression).
4. Assert error envelopes carry `code` / `message` / `trace_id` (observability contract).
5. Assert the Vercel `/patient` page returns 200 with title "CareSetu" and the served JS chunk inlines the backend base URL and the demo-banner strings (guards the trailing-slash and env-inlining bugs found during DEPLOY-7).

Pacing note: the flow makes ~4 auth-surface calls from one runner IP per window - safely under the 10/60 s limiter (plan §3.D). Reads `LIVE_BACKEND_URL` / `LIVE_FRONTEND_URL` repo variables (created by TEST-A2). Runs on merge (+ nightly via TEST-NIGHTLY).

Acceptance criteria (verbatim):

- `scripts/live_smoke.py` passes all five steps above against the live stack with a clean run
- The cooldown case is handled by waiting out the 60 s window and retrying, not by failing
- A deploy.yml job after deploy-render runs the smoke and hard-fails on any step
- The script works with repo-variable URLs (or equivalent env), and its auth-surface call count stays under the limiter

## Read-list (in order)

1. Plan `docs/plans/test-suite-plan/production-test-suite-plan.md` §2 (per-IP limiter, cold start) + §3.D + §5 - the five steps, cooldown rule, pacing (~0.6K).
2. `docs/agents/briefs/DEPLOY-7-provision-verify-demo.md` + issue #117 - the manual verification flow being automated (register -> OTP banner -> verify -> session -> protected route) (~0.6K).
3. `tests/e2e/auth-loop.spec.ts` - the canonical patient-flow call sequence + the 60 s cooldown wait-and-retry pattern to mirror (~0.7K).
4. `apps/backend/app/main.py` - CORS config (allowlist-driven ACAO echo), DEMO_MODE OTP read-back gating, `/health`, `/v1/me` + `MeResponse`, error envelope shape (~0.7K).
5. `apps/frontend/src/components/auth/otp/PatientAuthWizard.tsx` - the demo-banner strings and how `NEXT_PUBLIC_DEMO_MODE` / `NEXT_PUBLIC_API_BASE_URL` get inlined into the served JS chunk (~0.5K).
6. The TEST-A2 brief - `LIVE_BACKEND_URL` / `LIVE_FRONTEND_URL` wiring to read (~0.2K).
7. `.github/workflows/deploy.yml` - post-deploy-render job sequencing (~0.5K).

## Do NOT read

- `docs/archive/`, unrelated module specs, Lighthouse/ZAP/SBOM sections.

## Baseline verify (must pass before the first edit)

- `npm run lint`, `npm run typecheck`, `npm run test:unit`, `npm run migration-check` (all green on 2026-08-15).

## Done-verify (acceptance criteria → commands)

- Green deploy.yml run with the live smoke passing; `python scripts/live_smoke.py` passing locally with live env values.

## Handoff notes

- Blocked by #134 (TEST-A2) - reads `LIVE_BACKEND_URL` / `LIVE_FRONTEND_URL` and reuses A2's post-deploy-render job slot. Do NOT start before that brief's work merges.
- Registering `+91 9000000001` goes through the existing-phone login branch - the smoke must wait out any 60 s resend cooldown and retry, exactly like `auth-loop.spec.ts` does.
- CORS echo is allowlist-driven: Starlette returns `access-control-allow-origin` only when the request `Origin` is in the configured `CORS_ALLOWED_ORIGINS` (localhost:3000 + env). The smoke sends the Vercel `Origin` header, so the deployed `CORS_ALLOWED_ORIGINS` must include the Vercel URL - if the echo asserts fail, check that env value, not the middleware.
- ~4 auth-surface calls per runner-IP window - keep it under the 10/60 s limiter; never loop the auth flow.
- Step 5 is a page-content assertion (title + inlined strings in the served JS), not just a status check - guards the env-inlining regressions from DEPLOY-7.
- The Vercel build settles asynchronously from deploy-render - the job may need to wait/poll for `/patient` to serve before step 5.
