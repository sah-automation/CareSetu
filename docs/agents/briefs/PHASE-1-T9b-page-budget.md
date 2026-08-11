# Brief - PHASE-1 T9b Page-budget gate

**Ticket:** #34 · **Parent:** #16 · **Refreshed:** 2026-08-11
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The `NFR-003` gate: a measurement script that builds, serves, and measures initial-route payload (HTML + JS + CSS) per channel, asserting <= 1.5 MB each, wired into CI.

Acceptance criteria:

- [ ] Measurement script reports per-channel initial-route payload
- [ ] Each channel <= 1.5 MB budget
- [ ] CI job runs the gate on every PR

## Read-list (in order)

1. Issue #16 Implementation Decisions - channels decision: `measure-pages.cjs` builds, serves, and measures initial-route payload (HTML + JS + CSS) per channel, asserting <= 1.5 MB each in CI; page-budget runs in CI after a production build (~0.5K).
2. `docs/roadmap/implementation-roadmap.md` §2.1 (line 117) + §6 NFR-003 in `docs/prd/project-prd.md` - the gate: each channel's hello-world route renders under the 1.5 MB page weight (`NFR-003`) (~1K).
3. Sibling brief `docs/agents/briefs/PHASE-1-T9a-channel-routes.md` - the three channels are `/patient`, `/partner`, `/operator` route groups under `apps/frontend/src/app/`; keep pages dependency-free and small; the measurement script is T9b's deliverable (~1K).
4. `scripts/migration-check.cjs` - the existing gate-script pattern to mimic: node CJS at repo root `scripts/`, spawnSync, clear PASS/FAIL output, `process.exit(0/1)` (~1K).
5. Root `package.json` + `apps/frontend/package.json` + `.github/workflows/ci.yml` - where the gate hooks in: add a root `npm run check:pages` script and a `page-budget` CI job (job pattern follows the existing `unit`/`typecheck` jobs: checkout, setup-node 24, `npm ci`) (~1K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/backend/`, `tests/`. No backend or Python.

## Baseline verify (must pass before the first edit)

- `npm run build -w @caresetu/frontend` (root `npm run build` does NOT exist yet - builds are run via the workspace)
- `npm run test:unit:frontend`

## Done-verify (acceptance criteria -> commands)

- `npm run check:pages` - exits 0, prints a per-channel payload table with each channel <= 1.5 MB
- `npm run typecheck:frontend`
- `npm run lint:frontend`
- CI: `page-budget` job in `.github/workflows/ci.yml` runs `npm run check:pages` on every PR

## Handoff notes

- The three channel routes exist from T9a (#33) and are static hello-world pages; the whole app weighs well under 1.5 MB today, so the gate's job is to catch regressions, not today's numbers.
- Measurement approach (from parent #16): build (`next build` via the workspace), serve (`next start` on a local port), fetch each channel's HTML with `Accept-Encoding: identity` (page weight is measured uncompressed), parse the HTML for external JS (`<script src>`) and CSS (`<link rel="stylesheet">`) assets, fetch each asset, sum bytes, assert each channel's total <= 1.5 MB (1,572,864 bytes).
- Script lives at `scripts/measure-pages.cjs` and must be cross-platform (Node 24 in CI on Linux; Windows locally). Kill the `next start` process tree in a `finally` (taskkill /T /F on win32).
- Baselines verified green on 2026-08-11; `next build` outputs the three static routes + `/_not-found`.
