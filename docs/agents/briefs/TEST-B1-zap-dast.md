# Brief - 135 TEST-B1 - ZAP DAST on local instance

**Ticket:** #135 · **Parent:** #126 (TEST-SUITE) · **Refreshed:** 2026-08-15
**Reading surface:** ~2.5K tokens (budget 10K) - within budget

## Scope

DAST baseline (the plan deliberately scopes "full pentest" out - §8): a new `ci.yml` job runs an OWASP ZAP **API scan** against the locally-built app's `/openapi.json`. Fails on HIGH/CRITICAL alerts; MEDIUM/LOW are reported as artifacts for review. Runs against a rate-limit-disabled local instance (the same posture TEST-A1 establishes) so ZAP's probes of the auth surface do not 429. ZAP needs a JRE on the runner - add an explicit install step, same treatment as k6 in TEST-A1. Runs on PR + merge (+ nightly via the ci.yml gate in TEST-NIGHTLY).

Acceptance criteria (verbatim):

- A ci.yml job installs a JRE + ZAP, boots the local rate-limit-disabled instance, and API-scans `/openapi.json`
- HIGH/CRITICAL alerts fail the job; MEDIUM/LOW are uploaded as artifacts (pass + artifact)
- The scan hits the auth surface without tripping the rate limiter (posture matches TEST-A1)
- The run is bounded so CI runtime stays within the plan's upper-bound estimate

## Read-list (in order)

1. The TEST-A1 brief (`docs/agents/briefs/TEST-A1-ci-regression-load-test.md`) - the local-instance boot harness to reuse (Postgres service, mock SMS, `GATEWAY_RATE_LIMIT_ENABLED=false`) and the explicit-install precedent (~0.3K).
2. `.github/workflows/ci.yml` - job patterns: the Postgres 16-alpine service block, `uv sync` + `uv run --directory apps/backend`, and where the new job slots; the artifact-upload pattern (~1K).
3. Plan `docs/plans/test-suite-plan/production-test-suite-plan.md` §3.B1 + §5 - API-scan scope, HIGH/CRITICAL fail posture, MEDIUM/LOW artifacts, bounded runtime (~0.4K).
4. `apps/backend/app/main.py` - `/openapi.json` exposure on the local instance so the API scan can target it (~0.5K).

## Do NOT read

- `docs/archive/`, unrelated module specs, the frontend.

## Baseline verify (must pass before the first edit)

- `npm run lint`, `npm run typecheck`, `npm run test:unit`, `npm run migration-check` (all green on 2026-08-15).

## Done-verify (acceptance criteria → commands)

- Green ci.yml run with the ZAP job passing and its scan artifact present.

## Handoff notes

- Blocked by #127 (TEST-A1) - boot the instance the same way (rate limit disabled via env, never by editing `config.py` defaults). Do NOT start before that brief's work merges.
- ZAP requires a JRE on the runner - explicit install step (e.g. `eclipse-temurin` setup action), exactly parallel to k6's install step in TEST-A1.
- The scan is an API scan against `/openapi.json` (the ZAP API-scan mode), not a full-site crawl.
- MEDIUM/LOW findings upload as artifacts for human review but must NOT fail the job; HIGH/CRITICAL fail it.
- Keep the runtime bounded (plan §2 ~17 min/merge upper bound) - the API scan is small; do not add deep-crawl stages.
