# Brief - PHASE-1 T9a Channel hello-world routes

**Ticket:** #33 · **Parent:** #16 · **Refreshed:** 2026-08-11
**Reading surface:** ~3.5K tokens (budget 10K) - within budget

## Scope

Three role-scoped route groups (`/patient`, `/partner`, `/operator`) in the shared Next.js codebase, each rendering a hello-world page. A vitest smoke test asserts each route renders.

Acceptance criteria:

- [ ] `/patient`, `/partner`, `/operator` each render a hello-world page
- [ ] Route groups are role-scoped in one Next.js codebase (one deploy)
- [ ] Vitest smoke test covers the three routes
- [ ] `tsc --noEmit` + eslint green

## Read-list (in order)

1. `docs/architecture/internal-modules.md` §1 - frontend strategy: one shared Next.js codebase with role-scoped route groups, channels are containers not domain modules (~1K).
2. Issue #16 Implementation Decisions - channels decision: three role-scoped route groups in the one Next.js deploy, each with a hello-world route; the sibling T9b (#34) measures these routes' payload (~0.5K).
3. The frontend package (`apps/frontend`) conventions - package.json scripts, tsconfig (`@/*` path alias), vitest config (jsdom + `src/**/*.test.{ts,tsx}`), eslint config, the harness test that already passes (~2K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/backend/`, `tests/`.

## Baseline verify (must pass before the first edit)

- `npm run typecheck:frontend`
- `npm run test:unit:frontend`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` (smoke test renders all three routes)
- `npm run typecheck:frontend`
- `npm run lint:frontend`

## Handoff notes

- The frontend package is a bare skeleton today: no `app/` dir, only `src/harness.test.ts`. The three routes are the first real pages.
- Routes land under `src/app/` with route-group folders; T9b (#34) measures their initial-route payload against the 1.5 MB `NFR-003` gate, so keep pages dependency-free and small.
- E2E/Playwright arrives in a later ticket; the smoke test is vitest component-rendering against jsdom (per coding-standards §6).
- Baselines verified green on 2026-08-11.
