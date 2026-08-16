# Brief - 131 TEST-C2 - axe-core accessibility scan in e2e

**Ticket:** #131 · **Parent:** #126 (TEST-SUITE) · **Refreshed:** 2026-08-15
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

Accessibility regression guard in the existing Playwright e2e suite: add `@axe-core/playwright` and assert **no violations** on the auth wizard and the patient page. The e2e already boots a real local stack, so the scan is deterministic. Runs wherever the e2e job runs (PR + merge + nightly via the ci.yml gate in TEST-NIGHTLY).

Acceptance criteria (verbatim):

- `@axe-core/playwright` is a frontend dev dependency
- The e2e suite runs an axe scan on the patient auth wizard and asserts zero violations
- The e2e job in `ci.yml` is unchanged in shape (no new job - the assertions ride the existing e2e job)

## Read-list (in order)

1. `tests/e2e/auth-loop.spec.ts` - the existing auth-wizard flow (goto `/patient`, phone step, OTP step, authenticated home) and the cooldown wait-retry helper; where the axe assertions plug in (~1K).
2. `apps/frontend/src/components/auth/otp/PatientAuthWizard.tsx` - the wizard's renderable stages the scan targets (phone step, OTP step, `AuthenticatedHome`) (~0.6K).
3. Plan `docs/plans/test-suite-plan/production-test-suite-plan.md` §3.C2 - "no violations on the auth wizard and the patient page" (~0.2K).
4. Root `package.json` - where `@axe-core/playwright` joins devDependencies (next to `@playwright/test`) (~0.1K).

## Do NOT read

- Backend modules, `docs/archive/`, Lighthouse/ZAP/SBOM sections, the vitest wizard tests.

## Baseline verify (must pass before the first edit)

- `npm run lint`, `npm run typecheck`, `npm run test:unit` (all green on 2026-08-15).

## Done-verify (acceptance criteria → commands)

- `npm run test:e2e` passes locally with the axe assertions included.

## Handoff notes

- `@axe-core/playwright` is NOT currently a dependency; `axe-core` exists only transitively via `eslint-plugin-jsx-a11y`. Add the package at the repo root (where `@playwright/test` lives) or in `apps/frontend`, matching where the repo keeps e2e test tooling.
- The scan runs against the already-booted local stack (Playwright webServer boots frontend on :3000 + backend on :8000) - no new boot harness.
- The wizard renders `null` until hydration (`flow.state.hydrated`), and the demo banner only shows in `NEXT_PUBLIC_DEMO_MODE=true` - run the axe assertions only after the target stage is visible, mirroring how the existing spec waits on headings/buttons.
- No ci.yml shape change: the assertions ride the existing e2e job.
