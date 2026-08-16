# Brief - 134 TEST-A2 - Live load sweep

**Ticket:** #134 · **Parent:** #126 (TEST-SUITE) · **Refreshed:** 2026-08-15
**Reading surface:** ~2.5K tokens (budget 10K) - within budget

## Scope

A tolerant live production-stack health sweep: k6 against the live backend, targeting only the non-rate-limited surface - `/health` and `/v1/me` (the per-IP auth limiter makes hammering `/v1/auth/*` meaningless - plan §2). A warm-up request runs first (Render free cold start), then 20 VUs for 90 s against `/v1/me` with a shared minted session token. Thresholds: error rate < 2%, p95 < 2.5 s - tolerant of free-tier shared CPU and cold starts; a health sweep, not a capacity test.

Token minting must use a **dedicated test phone** distinct from the seeded demo phone `+91 9000000001`, so the live-load job never races the live smoke (TEST-D) on the 60 s per-phone resend cooldown. The minted token comes from the live register -> dev/otp -> verify -> session flow.

This is the first live job: it creates the GitHub **repo variables** `LIVE_BACKEND_URL` / `LIVE_FRONTEND_URL` (the Render and Vercel URLs) that TEST-B2 and TEST-D reuse. Runs as a deploy.yml job after `deploy-render` on merge (+ nightly later via TEST-NIGHTLY).

Acceptance criteria (verbatim):

- A deploy.yml job (after deploy-render) runs the warm-up + 20 VU / 90 s sweep against the live backend and enforces error rate < 2%, p95 < 2.5 s
- The sweep targets `/health` + `/v1/me` only (never the auth surface)
- The session token is minted for a dedicated test phone, distinct from `+91 9000000001`, and reused by all VUs
- `LIVE_BACKEND_URL` / `LIVE_FRONTEND_URL` repo variables exist and the job reads them
- The k6 report is uploaded as a run artifact

## Read-list (in order)

1. Plan `docs/plans/test-suite-plan/production-test-suite-plan.md` §2 (per-IP limiter, Render cold start) + §3.A2 + §5 posture (~0.6K).
2. The TEST-A1 brief (`docs/agents/briefs/TEST-A1-ci-regression-load-test.md`) - the k6 harness + `npm run test:load` + install step it reuses (implemented by then) (~0.3K).
3. `.github/workflows/deploy.yml` - job sequencing after `deploy-render`, how `secrets.SUPABASE_DATABASE_URL` flows, and the pattern for reading repo vars (~0.6K).
4. `apps/backend/app/main.py` - `/health`, `/v1/me`, and the dev/otp read-back gating (demo mode) the token-mint uses (~0.5K).
5. `.github/workflows/ci.yml` - k6 install precedent if TEST-A1's job already landed it (~0.4K).

## Do NOT read

- `docs/archive/`, unrelated module specs, the frontend.

## Baseline verify (must pass before the first edit)

- `npm run lint`, `npm run typecheck`, `npm run test:unit`, `npm run migration-check` (all green on 2026-08-15).

## Done-verify (acceptance criteria → commands)

- A green deploy.yml run with the A2 job passing and its k6 report artifact; `npm run test:load` unaffected.

## Handoff notes

- Blocked by #127 (TEST-A1) - reuse its k6 install + boot harness + thresholds pattern. Do NOT start before that brief's work merges.
- Create the `LIVE_BACKEND_URL` / `LIVE_FRONTEND_URL` repo **variables** (not secrets) - TEST-B2 (#136) and TEST-D (#137) read the same names.
- The token must be minted from a dedicated phone (e.g. `+91 9000000002` or a documented test phone) - never `+91 9000000001` (the seeded demo phone TEST-D registers), or the two jobs race the 60 s resend cooldown.
- Warm-up request precedes the sweep to absorb Render's ~1 min cold start; thresholds are tolerant on purpose (plan §3.A2 - health sweep, not capacity test).
- `/v1/me` needs a valid Bearer token - all 20 VUs share the single minted token; `GET /v1/auth/*` is off-limits in the scenario.
