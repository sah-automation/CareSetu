# Brief - 705 B5b - Nightly scheduled workflow + backfill + budget reset

**Ticket:** #705 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~7.2K tokens (budget 10K) - within budget

## Scope

Run the rollup on a schedule and backfill it. Add a nightly scheduled workflow (GitHub Actions, matching the existing backup-drill workflow) that connects via a secret and invokes the B5a rollup, because the Render free web process sleeps at ~15 minutes idle and an in-process cron is unreliable. The first run backfills all existing AI-job history; subsequent runs process the previous day. Include the monthly budget-period reset on `obs_ai_cost_budget`.

### Acceptance criteria

- [ ] A scheduled workflow invokes the rollup job; it does not depend on the web process being awake.
- [ ] First run backfills existing AI-job history; later runs process the previous day (idempotent on re-run).
- [ ] Budget period rolls over on schedule.
- [ ] Workflow config validated (lint) and documented in the deployment plan's env section.
- [ ] `npm run lint`; `npm run test:unit:backend` pass.

Blocked by #692 child B5a (rollup engine).

## Read-list (in order)

1. B5a rollup invocation seam (the runnable entrypoint + `run_rollup(target_date)`), its backfill decision, and the budget-period field on `obs_ai_cost_budget` - what the workflow calls and how idempotent re-runs are guaranteed. (~1.2K)
2. `.github/workflows/backup-drill.yml` - the schedule + `workflow_dispatch` + `concurrency` group + secret gate + hard-fail-on-missing-secret pattern to copy. (~2.5K)
3. `docs/plans/deployment-plan/portfolio-deployment-plan.md` §5.1/§5.2 (Render env vars) and §6.2 (GitHub Actions secrets) - where the new secret/env var is documented. (~1.5K)
4. `docs/plans/plan-phase14-observability.md` §8 - backfill rule ("first run all AI history, later previous day") and the GitHub-Action-over-in-process-cron rationale (Render sleep). (~0.8K)
5. `modules/intake/budget_meter.py` `_MONTH_START` / `read_spend_paise` - the calendar-month window semantics the budget reset must match. (~0.7K)
6. `package.json` scripts + `.pre-commit-config.yaml` - what the ticket's `npm run lint` actually validates on a workflow file. (~0.5K)

## Do NOT read

- Anything outside the read-list (frontend, consumer internals, unrelated workflows such as nightly/live-verify beyond the backup-drill pattern, other modules).

## Baseline verify (must pass before the first edit)

- `npm run lint` - the ticket gate (pre-commit: gitleaks, ruff, bandit, prettier, whitespace).
- `npm run test:unit:backend` - PASS (2925 passed, measured 2026-10-12).

## Done-verify (acceptance criteria → commands)

- `npm run lint` - PASS (workflow YAML passes prettier/whitespace; no secret committed).
- `npm run test:unit:backend` - PASS.
- `npm run test:integration` - if a native Postgres is reachable (skips otherwise): a rollup run against seeded AI-job history produces the expected aggregate rows; a second run for the same day is idempotent; the budget period rolls over on the schedule.
- `.github/workflows` - the new workflow parses (a manual `workflow_dispatch` dry run or local YAML parse).

## Handoff notes

- Copy `backup-drill.yml`'s shape: top-level `on: schedule:` cron + `workflow_dispatch`, a `concurrency` group, `permissions: contents: read`, `env: DATABASE_URL: ${{ secrets.SUPABASE_DATABASE_URL }}`, and an explicit "assert the secret is set" step that hard-fails rather than passing silently.
- The workflow must stand alone (checkout + toolchain) and invoke B5a's runnable entrypoint with the DB secret - it must not depend on the Render web process (plan §8: free web sleeps at ~15 min idle).
- Backfill-vs-daily: drive this from state persisted by the rollup (e.g. a last-run marker), not from workflow timing, so the "first run backfills all AI-job history, later runs the previous day" rule is testable and re-run safe (idempotent for a given date).
- Budget reset: match the budget meter's Postgres calendar-month window (`date_trunc('month', now())`), and document the annual/monthly cron choice alongside the Reset.
- Config discipline (coding-standards §9): any new secret gets a default-free entry in `.env.example` comments and a row in the deployment plan's GitHub-secrets + Render-env tables in the same change; never commit a value.
