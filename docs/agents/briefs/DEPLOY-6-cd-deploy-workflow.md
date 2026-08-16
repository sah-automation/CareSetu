# Brief - 116 DEPLOY-6 - CD workflow (deploy.yml)

**Ticket:** #116 · **Parent:** plan doc `docs/plans/deployment-plan/portfolio-deployment-plan.md` · **Refreshed:** 2026-08-15
**Reading surface:** ~4.5K tokens (budget 10K) - within budget

## Scope

Continuous deployment on push to `main` (+ manual dispatch): `deploy.yml` runs gated on green CI, with `concurrency: deploy`, migrates the Supabase database (`alembic upgrade head` against `SUPABASE_DATABASE_URL`), seeds it (`python -m scripts.seed_demo`), then fires the Render deploy hook. Vercel deploys itself from the same push, so the workflow only manages migrate + seed + Render. The plan documents the tolerance for a Vercel build racing the migration.

Acceptance criteria (verbatim):

- Workflow triggers on push to `main` and `workflow_dispatch`, with a single in-flight deploy (concurrency group)
- Gate job requires green CI before CD proceeds
- Migrate + seed jobs run against `secrets.SUPABASE_DATABASE_URL`; Render hook fired via `secrets.RENDER_DEPLOY_HOOK_URL`
- Workflow YAML validates (manual review / actionlint); no hardcoded secrets

## Read-list (in order)

1. Plan §6.1, §6.2, §5.1 - the job layout, the secrets, and the Supabase context (~1.5K).
2. `.github/workflows/ci.yml` (whole) - how jobs install uv, run backend pytest/mypy, and are named; the deploy gate must reference the same green conditions (~3K).

## Do NOT read

- Alembic revisions, frontend build internals, app source, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run lint` (currently all pre-commit hooks pass)

## Done-verify (acceptance criteria → commands)

- Workflow YAML parses (a YAML load of `.github/workflows/deploy.yml`) and the concurrency/secrets/needs wiring is consistent on review.
- Full run is validated in DEPLOY-7 after provisioning (secrets + Render hook exist).

## Handoff notes

- Two secrets are referenced but do NOT exist yet: `SUPABASE_DATABASE_URL` and `RENDER_DEPLOY_HOOK_URL` are created in DEPLOY-7 - the workflow must be written so a missing secret fails the run loudly (default GitHub behaviour) rather than being silently skipped.
- Commands run from the repo root, mirroring ci.yml: `uv sync --project apps/backend`, then `uv run --project apps/backend alembic -c apps/backend/alembic.ini upgrade head` and `uv run --project apps/backend python -m scripts.seed_demo` (both with `DATABASE_URL` set from the secret).
- The Render hook fires with a plain `curl -X POST "${{ secrets.RENDER_DEPLOY_HOOK_URL }}"`.
- Vercel is deliberately NOT in the workflow - it deploys from the same push. Document the ordering tolerance (a Vercel build may race the migration; the app tolerates a 500 envelope and retry) in a workflow comment.
- Gate job: `ci.yml` has no `on: workflow_call`, so `uses: ./.github/workflows/ci.yml` will not work as a reusable workflow as-is. Prefer a `needs:` chain on the repo's required checks (or add `workflow_call` to ci.yml in the same change) - decide and note it in the PR description.
