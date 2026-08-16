# Brief - 138 TEST-NIGHTLY - Nightly regression workflow

**Ticket:** #138 · **Parent:** #126 (TEST-SUITE) · **Refreshed:** 2026-08-15
**Reading surface:** ~1.5K tokens (budget 10K) - within budget

## Scope

The nightly regression workflow that catches drift between merges: a new `nightly.yml` cron (nightly schedule, also manually dispatchable) runs the full live-stack suite:

- The deterministic set via a `ci.yml` call (the gate) - which by then covers TEST-A1, TEST-B1, TEST-B4, TEST-C1, TEST-C2.
- The live jobs against the live stack: TEST-A2 (live load), TEST-B2 (security posture), TEST-D (live smoke, hard fail).

Schedule and concurrency should be set so a nightly run is an upper-bound on minutes, per plan §2. This ticket only wires already-built jobs together - it must not change any job's behavior, only invoke it on a schedule.

Acceptance criteria (verbatim):

- `nightly.yml` runs on a cron schedule and is manually dispatchable
- It calls the ci.yml gate (deterministic set incl. A1/B1/B4/C1/C2) and runs the live jobs A2, B2, D against the live stack
- A manual dispatch of `nightly.yml` completes green with the live smoke passing
- Nothing in the individual jobs' behavior is changed - only their wiring into the schedule

## Read-list (in order)

1. Plan `docs/plans/test-suite-plan/production-test-suite-plan.md` §2 (runtime upper-bound) + §4 table (what runs nightly: A1, A2, B1, B2, B4, C1, C2, D) (~0.5K).
2. `.github/workflows/ci.yml` - the existing `workflow_call:` trigger block on `ci.yml` (deploy.yml already calls it as its gate) that nightly.yml reuses verbatim (~0.5K).
3. `.github/workflows/deploy.yml` - how the live jobs (A2/B2/D) are sequenced after deploy-render; nightly.yml must invoke the same jobs/scripts without their deploy steps (~0.5K).

## Do NOT read

- `docs/archive/`, unrelated module specs, the individual TEST-\* job internals (their behavior is fixed - this ticket only wires schedules).

## Baseline verify (must pass before the first edit)

- `npm run lint`, `npm run typecheck`, `npm run test:unit`, `npm run migration-check` (all green on 2026-08-15).

## Done-verify (acceptance criteria → commands)

- Manual dispatch of `nightly.yml` green end-to-end with the live smoke passing.

## Handoff notes

- Blocked by #127 (A1), #130 (C1), #131 (C2), #135 (B1), #134 (A2), #136 (B2), #137 (D) - this is the LAST ticket in the suite; do NOT start until all seven blockers have landed and their jobs exist in ci.yml/deploy.yml.
- `ci.yml` already exposes `workflow_call:` (used by deploy.yml's gate) - nightly.yml calls the same gate; nothing in ci.yml or deploy.yml job behavior may change, only invocation.
- The live jobs (A2/B2/D) live in deploy.yml after deploy-render; nightly.yml must invoke the equivalent job steps without the migrate/seed/deploy steps (the live stack is already deployed) - reuse the same scripts (`live_smoke.py`, `security_posture.py`, the A2 k6 scenario) and the `LIVE_BACKEND_URL` / `LIVE_FRONTEND_URL` variables.
- Set a cron schedule + a concurrency group so runs don't stack; keep the whole run within the plan's runtime upper bound.
