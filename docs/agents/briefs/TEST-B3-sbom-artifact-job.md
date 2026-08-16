# Brief - 129 TEST-B3 - SBOM artifact job

**Ticket:** #129 · **Parent:** #126 (TEST-SUITE) · **Refreshed:** 2026-08-15
**Reading surface:** ~1.5K tokens (budget 10K) - within budget

## Scope

Supply-chain hygiene artifact: a new `ci.yml` job generates an SBOM - `pip-cyclonedx` for the backend, `@cyclonedx/cyclonedx-npm` for the frontend - and uploads it as a build artifact (pass + artifact posture). The advisory gates (pip-audit, npm audit, gitleaks, bandit) already run in the existing scan job and are unchanged. Runs on PR + merge.

Acceptance criteria (verbatim):

- A ci.yml job emits a cyclonedx SBOM covering the backend Python deps and one covering the frontend npm deps
- Both SBOMs are uploaded as build artifacts (downloadable from the run)
- The job is a pass + artifact gate (fails only if generation fails), not an advisory gate

## Read-list (in order)

1. `.github/workflows/ci.yml` - the existing `scan` job (tool install + `uv sync` + `npm ci` precedent) and where the new sbom job slots into the workflow; the artifact-upload pattern if one exists (~0.8K).
2. `apps/backend/pyproject.toml` + `apps/frontend/package.json` - the dependency sources the SBOMs must cover (~0.5K).
3. Plan `docs/plans/test-suite-plan/production-test-suite-plan.md` §3.B3 + §5 - the pass + artifact posture (~0.2K).

## Do NOT read

- `docs/archive/`, backend/frontend source internals, the scan job's advisory logic (unchanged).

## Baseline verify (must pass before the first edit)

- `npm run lint`, `npm run typecheck`, `npm run test:unit` (all green on 2026-08-15).

## Done-verify (acceptance criteria → commands)

- Green ci.yml run on the PR with both SBOM artifacts present in the run's artifact list.

## Handoff notes

- `pip-cyclonedx` and `@cyclonedx/cyclonedx-npm` are NOT currently dependencies of the repo - the job installs/invokes them (e.g. `uvx pip-cyclonedx` after `uv sync --project apps/backend`, `npx @cyclonedx/cyclonedx-npm` after `npm ci`).
- Frontend SBOM is generated from the workspace root lockfile (`package-lock.json`); run it from `apps/frontend` so `@cyclonedx/cyclonedx-npm` resolves the workspace's dependency graph.
- The `scan` job (gitleaks/bandit/pip-audit/npm audit) must remain byte-for-byte unchanged - this ticket only ADDS an sbom job.
- No secrets are needed; the job never touches the auth surface or a live instance.
