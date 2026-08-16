# Brief - 130 TEST-C1 - Lighthouse gate on local build

**Ticket:** #130 · **Parent:** #126 (TEST-SUITE) · **Refreshed:** 2026-08-15
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

Make AMB-001 ("works over 4G") verifiable against NFR-PERF-001: a new `ci.yml` job runs Lighthouse against a **locally-built** frontend (deterministic - no cold-start variance), mobile emulation with simulated throttled 4G. Thresholds: Performance >= 85, Accessibility >= 90, Best Practices >= 90, SEO >= 90. PWA checks are deliberately NOT gated (the frontend has no manifest/service-worker/icons, and modern Lighthouse scores no PWA category - plan §3.C1). Runs on PR + merge (+ nightly via the ci.yml gate in TEST-NIGHTLY).

Runner note: the e2e job already installs Playwright's Chromium; point Lighthouse at it via `CHROME_PATH` instead of a second browser download.

Acceptance criteria (verbatim):

- A ci.yml job builds the frontend locally, serves it, and runs Lighthouse with mobile emulation + throttled 4G
- Thresholds enforced: Performance >= 85, Accessibility >= 90, Best Practices >= 90, SEO >= 90
- PWA checks are explicitly not gated, and the Lighthouse report is uploaded as an artifact
- Uses the already-installed Chromium via `CHROME_PATH` (no second browser download)

## Read-list (in order)

1. `.github/workflows/ci.yml` - the `page-budget` job (local `npm run build` + `next start` on a port - the serve pattern to reuse) and the `e2e` job's `npx playwright install --with-deps chromium` step (where Chromium lands, so `CHROME_PATH` can point at it) (~1K).
2. `scripts/measure-pages.cjs` - how the existing gate builds + serves the frontend locally (`npm run build` then `next start`), the pattern the Lighthouse job mirrors (~0.6K).
3. Plan `docs/plans/test-suite-plan/production-test-suite-plan.md` §3.C1 + §5 - thresholds, no-PWA rationale, mobile emulation + 4G throttle (~0.4K).

## Do NOT read

- `docs/archive/`, backend modules, the wizard's component internals (the scan targets the built page, not source).

## Baseline verify (must pass before the first edit)

- `npm run lint`, `npm run typecheck`, `npm run test:unit`, `npm run build` (all green on 2026-08-15).

## Done-verify (acceptance criteria → commands)

- Green ci.yml run on the PR with the Lighthouse job passing and the report artifact present.

## Handoff notes

- The frontend has NO manifest/service-worker/icons and no PWA category today - do not add a PWA gate; if a PWA is added later, add the check back.
- `next start` must serve the built app on a free port (mirror `scripts/measure-pages.cjs`); Lighthouse then scans `http://localhost:<port>/patient`.
- Playwright's Chromium from the e2e install step lives under the runner's ms-playwright cache - `CHROME_PATH` must resolve that executable; do not download a second browser.
- The served app needs no backend for the scan to be meaningful (the wizard pages render client-side) - do not boot a backend unless the scan 404s without one.
