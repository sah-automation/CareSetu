# Brief - 136 TEST-B2 - Boundary security posture

**Ticket:** #136 · **Parent:** #126 (TEST-SUITE) · **Refreshed:** 2026-08-15
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

Live boundary security posture gate: `scripts/security_posture.py` checks the live Render backend and Vercel frontend URLs and asserts `NFR-SEC-001` - HTTPS only, TLS 1.2+, HSTS header, `X-Content-Type-Options`, no cleartext/legacy ciphers. Hard fail on merge + nightly (tolerant only in the sense of "fail only on clear regressions or availability" - the header checks themselves are hard).

Header-availability note (plan §3.B2): Render free may not emit `HSTS` / `X-Content-Type-Options` by default. Verify the live headers first and add edge header configuration at Render/Vercel if absent; the posture stays a hard fail per `NFR-SEC-001`. Reads `LIVE_BACKEND_URL` / `LIVE_FRONTEND_URL` repo variables (created by TEST-A2). Runs as a deploy.yml job after deploy-render on merge (+ nightly via TEST-NIGHTLY).

Acceptance criteria (verbatim):

- The script checks both live URLs and hard-fails on: any non-HTTPS scheme, TLS < 1.2, missing HSTS, missing `X-Content-Type-Options`, or a legacy/cleartext cipher
- Live headers are verified and any missing edge headers (e.g. on Render) are added so the checks pass on the real stack
- A deploy.yml job runs the posture check after deploy-render and hard-fails on violation
- The script reports which check/header failed with the observed value

## Read-list (in order)

1. Plan `docs/plans/test-suite-plan/production-test-suite-plan.md` §3.B2 + §5 - the exact header/cipher assertions and hard-fail posture (~0.4K).
2. `docs/standards/security-phii-standards.md` - `NFR-SEC-001` / `NFR-SEC-002` exact requirements (HTTPS only, TLS 1.2+, HSTS, X-Content-Type-Options, no legacy ciphers) (~0.5K).
3. `render.yaml` - current env/headers config for the Render service; where edge headers get added (~0.3K).
4. `.github/workflows/deploy.yml` - post-deploy-render job sequencing + how repo variables are read (~0.5K).
5. The TEST-A2 brief - `LIVE_BACKEND_URL` / `LIVE_FRONTEND_URL` variable wiring it establishes (~0.2K).

## Do NOT read

- `docs/archive/`, unrelated module specs, backend/frontend source internals.

## Baseline verify (must pass before the first edit)

- `npm run lint`, `npm run typecheck`, `npm run test:unit`, `npm run migration-check` (all green on 2026-08-15).

## Done-verify (acceptance criteria → commands)

- Green deploy.yml run with the posture job passing against the live URLs; the script's failure output names the failing header + observed value.

## Handoff notes

- Blocked by #134 (TEST-A2) - reads the `LIVE_BACKEND_URL` / `LIVE_FRONTEND_URL` repo variables A2 creates. Do NOT start before that brief's work merges.
- Render free may not emit `HSTS` / `X-Content-Type-Options` by default (plan §3.B2 note) - this ticket MUST add edge header config (Render service headers / Vercel config) if the live headers are missing, not weaken the check.
- TLS/cipher assertions need a TLS client in the script (e.g. `ssl` + `socket` with a probe, or an httpx/openssl-based handshake) - report observed protocol/ciphers on failure.
- The posture stays a hard fail; "tolerant" only means fail-on-clear-regression semantics, the header checks themselves are absolute.
