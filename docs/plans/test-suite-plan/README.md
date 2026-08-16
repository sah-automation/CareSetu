# Production Test Suite Plan - README (easy reference)

**Purpose:** take the live portfolio demo from "CI gate + manual click-through" to a production-grade verification pipeline - the tests a production engineer runs at production level, adapted to this project's free-tier stack (Render + Vercel + Supabase) and OSS-only rule (`NFR-001`).

## Files

| File                            | Read when                                                                                                                                                                                                                |
| :------------------------------ | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `production-test-suite-plan.md` | The full plan: constraints, the A-F suite mapped to production engineer activities, tool choices, pass/fail thresholds, ticket breakdown, execution order, deliberate exclusions. Start here for any test-pipeline work. |

## TL;DR - what the suite adds

| Workstream              | Tool                                                           | When               | Gate                                                                                                     |
| :---------------------- | :------------------------------------------------------------- | :----------------- | :------------------------------------------------------------------------------------------------------- |
| **A. Load/performance** | k6 (local regression + live)                                   | PR, merge, nightly | p95/p99/error thresholds                                                                                 |
| **B. Security**         | ZAP DAST, live posture script, SBOM, rate-limit test           | PR, merge, nightly | no HIGH/CRITICAL; HSTS/TLS present; 429 behavior                                                         |
| **C. Frontend quality** | Lighthouse (local build) + axe-core in e2e                     | PR, merge          | Perf >= 85, A11y >= 90, BP/SEO >= 90 (no PWA gate - no manifest/SW in the app today); no a11y violations |
| **D. Live smoke**       | `scripts/live_smoke.py` (the demo flow, live)                  | merge, nightly     | hard fail - this is the demo                                                                             |
| **E. DR drill**         | real `pg_dump` of Supabase -> encrypt -> restore -> round-trip | monthly cron       | hard fail                                                                                                |
| **F. Contract**         | backend OpenAPI vs frontend auth client shapes                 | PR, merge          | hard fail                                                                                                |

**Posture:** strict pass/fail on deterministic CI jobs (local instances); tolerant bounds on live free-tier jobs (cold starts, shared CPU); `live-smoke` is a hard fail everywhere it runs.

## Key constraints (why the suite is shaped this way)

- **Auth rate limiter is per-IP** (`/v1/auth/*`, 10 req/60 s, `app/gateway/rate_limit.py`): a live load test cannot exercise the auth flow from one source IP. Live load targets `/health` + `/v1/me` (outside the prefix); the auth flow gets a paced live smoke instead.
- **Free-tier variance:** Render cold-starts after ~15 min idle; Supabase pauses after 7 days idle. Live jobs warm up first and use tolerant thresholds.
- **Cost (`NFR-001`):** all tools are free/OSS. The repo is public, so GitHub Actions standard-runner minutes are free and unlimited; the suite adds roughly 17 min per merge run and 11 min per PR run (an upper bound, not a quota concern).

## Ticket breakdown (one per workstream)

T1 load (k6) -> T2 security (DAST + posture + SBOM + rate-limit) -> T3 frontend quality (Lighthouse + axe) -> T4 live smoke -> T5 DR drill -> T6 contract check. T2 -> T3 -> T6 serialize on `ci.yml`; T1/T4/T5 are independent.

Full details: see `production-test-suite-plan.md`.
