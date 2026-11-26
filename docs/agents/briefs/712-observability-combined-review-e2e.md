# Brief - 712 E - Combined review + E2E + CI gates-on/off

**Ticket:** #712 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

**What to build:** Run the combined review and the end-to-end proof once all Batch 1 tickets land. Review the combined implementation with the `/code-review` skill (standards + spec axes) and fix any bug found. Add the operator E2E: an operator opens the Observability tab against seeded data and follows a deep-link. Add the CI gate that exercises the vendor gates both on and off, so the no-op path cannot rot.

**Acceptance criteria**

- [ ] `/code-review` run over the combined Batch 1 changes; findings fixed or explicitly dispositioned.
- [ ] A Playwright E2E where an operator opens the Observability tab and sees populated data from the seeded observability schema, and follows a deep-link.
- [ ] CI builds the observability gates both on and off (no-op path does not rot).
- [ ] The full repo harness passes: `npm run lint`, `npm run typecheck`, `npm run test:unit:backend`, `npm run test:unit:frontend`, `npm run migration-check`, `npm run test:e2e`.

## Read-list (in order)

1. `docs/plans/plan-phase14-observability.md` §16 Verification + §17 Implementation order - the harness commands, new-test list, E2E shape, and the CI gates-on/off requirement. (~0.7K)
2. `tests/e2e/doctor-workspace.spec.ts` - the operator E2E leg pattern: real Next runtime over a live backend, `test.describe.configure({ mode: "serial" })`, seeded bootstrap operator, `APIRequestContext`, and row/deep-link navigation. Read the header + one representative leg, not the whole file. (~2.0K)
3. `.github/workflows/ci.yml` - the `page-budget` job (~line 128) and the general job shape (`needs: [changes]`, the `if: needs.changes.outputs.*` filters, setup-node/setup-python) to add the observability gates-on/off build job. (~1.8K)
4. `tests/e2e/README.md` + `playwright.config.ts` - how the backend boots and seeds (`scripts/e2e-backend.cjs`, `DISPATCHER_IN_PROCESS_ENABLED=true`), so the E2E can reach the seeded `observability` schema. (~0.8K)
5. `docs/agents/briefs/` - the sibling Batch-1 briefs (#708, #709, #710, and the backend A/B tickets) that name the interfaces this review audits. (~0.3K)

## Do NOT read

- `docs/archive/`.
- Unrelated modules or surfaces.
- The full `doctor-workspace.spec.ts` / full `ci.yml` (read the named slices only).

## Baseline verify (must pass before the first edit)

- `npm run lint` - PASS on the current tree.
- `npm run typecheck` - PASS on the current tree.
- `npm run migration-check` - PASS.
- `npm run test:unit:backend` - PASS (2925 passed).
- `npm run test:unit:frontend` - all 1910 tests in 133 files pass; the vitest process exits non-zero on a worker-timeout error (environment flake, not a test failure). Treat the suite as green.

## Done-verify (acceptance criteria → commands)

- `/code-review` run over the combined Batch 1 changes (standards + spec axes); findings fixed or dispositioned.
- `npm run lint`
- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run migration-check`
- `npm run test:e2e`

## Handoff notes

- The E2E mirrors `doctor-workspace.spec.ts`: serial mode, own browser context per test, bootstrap operator login (TOTP), and seeded data; add an observability seed so the tab renders populated rows and a resolvable deep-link.
- The CI gate must build the observability vendor gates **both on and off** - the env-gated no-op path is the thing that rots, so exercise it rather than only the configured path.
- Reviewer note: `/code-review` runs both axes in parallel and reports them side by side; sibling briefs are the spec axis's reference for each Batch-1 ticket's acceptance criteria.
