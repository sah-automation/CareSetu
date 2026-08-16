# Production Test Suite Plan: Free-Tier Portfolio

**Status:** planned (approved scope; code changes not yet implemented)
**Date:** 2026-08-15
**Upstream targets:** deployment plan (`docs/plans/deployment-plan/portfolio-deployment-plan.md`), `NFR-001` (cost floor, OSS only), `NFR-002` (security), `NFR-003`/`NFR-PERF-001` (performance), `NFR-PERF-004` (durability floor), IAM latency SLAs (`docs/architecture/internal-modules.md` §7: `validate_token` p95 < 100 ms, `verify_otp` p95 < 400 ms).
**Scope:** extend the live demo's verification from "9 CI jobs + manual click-through" to a production-grade test pipeline - the checks a production engineer runs at production level, relevant to this project, running on the existing free tiers at zero monthly cost.

---

## 1. Goal

Give the portfolio demo a production engineer's verification story:

- **Deterministic quality gates** on every PR and merge (local instances, strict thresholds, no flakiness from the free tier).
- **Production verification** on every merge to `main` (the live demo actually works, plus light live load and boundary security posture).
- **Nightly regression** against the live stack (catches drift between merges).
- **Monthly DR drill** operationalizing the backup/restore floor (`NFR-PERF-004`).
- **Supply-chain and contract hygiene** (SBOM artifact, OpenAPI vs frontend client contract).

Everything is OSS and free-tier (`NFR-001`); nothing adds paid infrastructure or paid tooling.

## 2. Constraints that shape the suite (verified in code)

| Constraint                  | Detail                                                                                                                  | Consequence                                                                                                                                                                 |
| :-------------------------- | :---------------------------------------------------------------------------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Auth rate limiter is per-IP | `RateLimitMiddleware` (`apps/backend/app/gateway/rate_limit.py`): `10 req/60 s` per client IP, prefix `/v1/auth/*` only | Live load cannot exercise the auth flow from one IP (429 after 10). Live load targets `/health` + `/v1/me` (outside the prefix); auth flow is covered by a paced live smoke |
| Render free cold start      | Spins down after ~15 min idle; first request ~1 min                                                                     | Live jobs warm up (one request) before measuring; live thresholds tolerate cold-start spikes                                                                                |
| Supabase free pauses        | Pauses after 7 days idle; no automated backups                                                                          | Monthly DR drill must flag (not silently pass) if the DB is paused; drill uses the session pooler connection                                                                |
| CI vs prod hardware         | GitHub runner and Render free differ wildly                                                                             | Load thresholds in CI are regression bounds on CI hardware, documented as such - not production SLAs                                                                        |
| GitHub Actions minutes      | The repo is **public**: standard-runner minutes are free and unlimited, so minutes are not a hard cap                   | Suite adds ~17 min per merge run, ~11 min per PR run, a few per nightly - an upper bound, kept so load/ZAP runtimes stay bounded                                            |

## 3. The suite (A-F) mapped to production engineer activities

### A. Performance and load testing

**A1 - CI regression load test (strict, on PR + merge + nightly).**
k6 against a local instance built the same way e2e does (throwaway Postgres, rate limiting disabled for the test instance - same `GATEWAY_RATE_LIMIT_ENABLED=false` posture as `playwright.config.ts`). Scenario = the patient flow: `register -> GET /v1/auth/dev/otp -> verify -> session -> /v1/me`, ramp 10 -> 50 VUs. The mock SMS adapter is in-process, so each VU reads its OTP over the HTTP dev/otp read-back (each VU uses its own phone).
Thresholds: error rate < 1%, p95 < 800 ms, p99 < 1.5 s. These are CI-hardware regression bounds, not the product SLAs from the whitebox docs.
CI install note: the k6 binary is not pre-installed on GitHub runners; `ci.yml` must install k6 (e.g. `grafana/k6-action` or a download step) before the scenario runs - same explicit-install treatment as ZAP's JRE step in B1.
Files: `scripts/loadtest/*.js`, `npm run test:load`.

**A2 - Live load (tolerant, on merge + nightly).**
k6 against the live backend, targets `/health` and `/v1/me` (non-rate-limited surface), with a shared minted session token. Warm-up request first; then 20 VUs for 90 s.
Thresholds: error rate < 2%, p95 < 2.5 s - tolerant of free-tier shared CPU and cold starts; this is a production-stack health sweep, not a capacity test.
Token-minting note: A2 mints its session token from a dedicated test phone distinct from the seeded demo phone `+91 9000000001`, so the live-load job never races the live smoke (D) on the 60 s per-phone resend cooldown.
Not included: hammering `/v1/auth/*` (per-IP limiter makes it meaningless) and soak/spike tests (free tier has no capacity headroom; the ROI is not there for a portfolio demo).

### B. Security

**B1 - DAST (strict, PR + merge + nightly).** OWASP ZAP **API scan** against the locally-built app's `/openapi.json`. Fails on HIGH/CRITICAL alerts; MEDIUM/LOW are reported as artifacts for review. Runs against a rate-limit-disabled local instance (same posture as A1) so ZAP's probes of the auth surface do not 429; ZAP needs a JRE on the runner (install step).
**B2 - Boundary security posture (hard fail on merge + nightly).** `scripts/security_posture.py` against live Render + Vercel URLs, asserting `NFR-SEC-001`: HTTPS only, TLS 1.2+, HSTS header, `X-Content-Type-Options`, no cleartext/legacy ciphers.

Header-availability note: Render free may not emit `HSTS`/`X-Content-Type-Options` by default. T2 verifies the live headers and adds edge header configuration at Render/Vercel if absent; the posture stays a hard fail per `NFR-SEC-001`.
**B3 - Supply chain (pass + artifact on PR + merge).** Generate an SBOM (`pip-cyclonedx` + `@cyclonedx/cyclonedx-npm`) published as a build artifact. Advisory gates already exist in CI (`pip-audit`, `npm audit`, gitleaks, bandit) - unchanged.
**B4 - Abuse protection (strict, PR).** The rate-limit contract (429 after N rapid auth calls, `Retry-After` header, shared error envelope, auth-surface-only counting, garbage-token spray exhaustion) is already covered by `tests/unit/test_gateway.py`; no new test needed there. One gap to close: TestClient always uses one client IP, so add a unit test asserting two different source IPs get independent buckets. Validates `NFR-SEC-004` ingress abuse protection.

Test technique: `TestClient` hardcodes a single client IP (`"testclient"`), so the two-IP test cannot go through TestClient - it invokes `RateLimitMiddleware.dispatch` directly with crafted `Request` scopes carrying different `client.host` values.

### C. Frontend quality and accessibility

**C1 - Lighthouse (strict, PR + merge).** Lighthouse on a **locally-built** frontend (deterministic - no cold-start variance), mobile emulation with simulated throttled 4G. Makes `AMB-001` ("works over 4G") verifiable against `NFR-PERF-001`.
Thresholds: Performance >= 85, Accessibility >= 90, Best Practices >= 90, SEO >= 90. PWA checks (manifest + service worker) are deliberately **not** gated: the current frontend has no manifest/service worker/icons, and modern Lighthouse no longer scores a PWA category - if the PWA is implemented later, add the check back.

Browser note: the runner already installs Playwright's Chromium for the e2e job; point Lighthouse at it via `CHROME_PATH` instead of a second browser download.
**C2 - Accessibility scan (strict, PR + merge).** `@axe-core/playwright` added to the existing Playwright e2e: assert no violations on the auth wizard and the patient page.

### D. Post-deploy live smoke (hard fail, merge + nightly)

`scripts/live_smoke.py` automates the manual DEPLOY-7 verification, after `deploy-render` and after Vercel's build settles:

1. Warm-up request, then `GET /health` -> 200 `{"status":"ok"}`.
2. Full live demo flow with the Vercel `Origin` header on every call: register `+91 9000000001` -> `GET /v1/auth/dev/otp` -> verify -> `POST /v1/auth/session` -> `GET /v1/me` with Bearer (asserts `roles: ["patient"]`).

   Cooldown note: register on the seeded phone goes through the existing-phone login branch, which honors the 60 s resend cooldown. If the smoke runs within 60 s of a prior OTP send to that phone (e.g. a deploy rerun right after a failed run), register answers `cooldown` - the smoke must wait out the window and retry rather than fail (mirrors the e2e's cooldown catch, `tests/e2e/auth-loop.spec.ts`).

   Availability tolerance: a transient 5xx or connection-level failure in the demo flow (e.g. the Render build/instance swap from the deploy hook) is retried within a bounded window, paced under the limiter - a deploy in flight is not a regression, exactly like B2 (section 5). 4xx answers, wrong outcomes, and window exhaustion are hard failures.

3. Assert `access-control-allow-origin` echoes the Vercel origin on every response (guards the CORS regression).
4. Assert error envelopes carry `code` / `message` / `trace_id` (observability contract).
5. Assert the Vercel `/patient` page returns 200 with title "CareSetu" and the served JS chunk inlines the backend base URL and the demo-banner strings (guards the trailing-slash and env-inlining bugs found during DEPLOY-7).

Pacing note: this flow makes ~4 auth-surface calls from one runner IP per window - safely under the 10/60 s limiter.

### E. DR drill (hard fail, monthly cron)

New scheduled workflow `backup-drill.yml` (monthly):

1. Real `pg_dump` of the live Supabase database over the session-pooler connection (`secrets.SUPABASE_DATABASE_URL`).
2. AES-256-encrypt the dump (passphrase from a secret), store as a workflow artifact.
3. Restore the dump into a throwaway Postgres service container in the job.
4. Assert the round-trip: demo identity present, row count checksum matches.

Operationalizes the boundary durability floor (`NFR-PERF-004`): restore validated, not just backup created. If Supabase has paused (7-day idle), the job fails loudly with a clear message instead of passing silently.

### F. Contract check (hard fail, PR + merge)

`scripts/contract_check.py` validates the frontend's auth client request/response shapes (`apps/frontend/src/lib/auth/api.ts`) against the backend OpenAPI schema (`/openapi.json`). Prevents the frontend/backend drift class of bug hit during DEPLOY-7 (field-name mismatch, 422s).

## 4. Where each check runs

| Check                         | PR  | Merge (deploy.yml) | Nightly (cron)  | Monthly (cron) |
| :---------------------------- | :-- | :----------------- | :-------------- | :------------- |
| Existing 9 CI jobs (gate)     | yes | yes (gate)         | yes (gate)      | -              |
| A1 load regression (local k6) | yes | yes                | yes             | -              |
| A2 live load                  | -   | yes                | yes             | -              |
| B1 ZAP DAST                   | yes | yes                | yes             | -              |
| B2 security posture (live)    | -   | yes                | yes             | -              |
| B3 SBOM                       | yes | yes                | -               | -              |
| B4 rate-limit test            | yes | yes                | yes             | -              |
| C1 Lighthouse (local build)   | yes | yes                | yes             | -              |
| C2 axe a11y                   | yes | yes                | yes             | -              |
| D live smoke                  | -   | yes (hard fail)    | yes (hard fail) | -              |
| E DR drill                    | -   | -                  | -               | yes            |
| F contract check              | yes | yes                | -               | -              |

## 5. Pass/fail posture

- **Strict** (deterministic, local instances, no free-tier flakiness): A1, B1, B3, B4, C1, C2, F.
- **Tolerant** (live free-tier jobs, fail only on clear regressions or availability): A2, B2.
- **Hard fail everywhere** (this is the demo / durability floor): D, E.
- D is hard-fail on genuine regressions (4xx, wrong outcomes, window exhaustion) but, like B2, absorbs availability: its bounded retry window re-runs the demo flow on a transient 5xx / connection failure from the Render build/instance swap, paced under the auth limiter (section 3.D).

## 6. Files (new and changed)

| File                                 | Purpose                                                       |
| :----------------------------------- | :------------------------------------------------------------ |
| `scripts/loadtest/*.js`              | k6 scenarios (patient flow, read sweep) + thresholds          |
| `scripts/live_smoke.py`              | post-deploy production verification (D)                       |
| `scripts/security_posture.py`        | live HSTS/TLS/header checks (B2)                              |
| `scripts/contract_check.py`          | OpenAPI vs frontend client validation (F)                     |
| `scripts/backup_drill.py`            | pg_dump -> encrypt -> restore -> round-trip (E)               |
| `package.json`                       | `test:load` script                                            |
| `.github/workflows/ci.yml`           | add A1, B1, B3, B4, C1, C2, F jobs                            |
| `.github/workflows/deploy.yml`       | add A2, B2 after deploy-render; add D (live smoke, hard fail) |
| `.github/workflows/nightly.yml`      | new: full live-stack suite on a cron schedule                 |
| `.github/workflows/backup-drill.yml` | new: monthly DR drill (E)                                     |
| `docs/plans/test-suite-plan/`        | this plan + README                                            |

## 7. Ticket breakdown and execution order

| Ticket | Workstream                  | Blocks / depends on                                        |
| :----- | :-------------------------- | :--------------------------------------------------------- |
| T1     | Load testing (k6): A1 + A2  | independent (own job in ci.yml)                            |
| T2     | Security: B1 + B2 + B3 + B4 | serializes ci.yml edits; lands first among ci.yml touchers |
| T3     | Frontend quality: C1 + C2   | after T2 (ci.yml)                                          |
| T4     | Live smoke: D               | after T2 (deploy.yml), needs live secrets                  |
| T5     | DR drill: E                 | independent (own workflow)                                 |
| T6     | Contract check: F           | after T3 (ci.yml)                                          |

**Order:** T1 -> T2 -> T3 -> T4 -> T5 -> T6 (T2 -> T3 -> T6 serialized on `ci.yml`; T1/T4/T5 parallelizable).

Each ticket is verified with the repo harness before merge (`npm run lint`, `npm run typecheck`, `npm run test:unit:backend`, `npm run test:unit:frontend`, `npm run migration-check`), and live jobs are verified by a green `deploy.yml` run with the live smoke passing.

## 8. Deliberately NOT included (senior judgment)

| Not included                                         | Why                                                                                                                   |
| :--------------------------------------------------- | :-------------------------------------------------------------------------------------------------------------------- |
| Chaos engineering on the free tier                   | Would take the demo down; the light equivalent (DB-down -> 5xx envelope, no crash) is already unit-tested             |
| Full penetration test                                | Paid and out of proportion for a portfolio demo; ZAP DAST (B1) is the baseline                                        |
| Geo / multi-region load testing                      | `NFR-003` targets 4G in India; Lighthouse 4G throttle (C1) covers the verifiable part                                 |
| Soak / spike load tests                              | Free tier has no capacity headroom; low ROI for a single-evaluator demo                                               |
| Synthetic uptime monitoring                          | Out of GitHub scope; optional external free service (e.g. UptimeRobot) can be added later without a plan change       |
| Performance budget on live (Lighthouse against live) | Cold starts make it non-deterministic; the local-build check (C1) is the gate, the live smoke (D) proves availability |

## 9. Cost and quota check (`NFR-001`)

All tools are free/OSS: k6, OWASP ZAP, Lighthouse CI (run locally, no external service), axe-core, cyclonedx. The repo is public, so GitHub Actions standard-runner minutes are free and unlimited; the estimated additions (~11 min per PR run, ~17 min per merge run, plus the nightly and monthly cron runs) are an upper bound to keep runtimes in check, not a quota concern. No paid provider is used anywhere in the suite.

## 10. How to run the suite locally

```text
npm run lint                  # pre-commit (gitleaks, ruff, bandit, prettier)
npm run typecheck             # mypy --strict (backend) + tsc --noEmit (frontend)
npm run test:unit             # pytest + vitest
npm run migration-check       # alembic single head + cross-schema FK scan
npm run test:e2e              # Playwright (includes axe a11y assertions after T3)
npm run test:load             # k6 regression load test (after T1)
python scripts/live_smoke.py   # live production smoke (after T4, needs .env values)
```

CI (`ci.yml`) runs the full deterministic set on every PR and merge; `deploy.yml` adds the live verification; `nightly.yml` and `backup-drill.yml` add the scheduled regression and DR drill.
