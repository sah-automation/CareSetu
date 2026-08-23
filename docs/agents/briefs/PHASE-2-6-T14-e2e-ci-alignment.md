# Brief - T14 E2E/CI alignment: page budgets, lighthouse re-baseline, axe coverage

**Ticket:** #205 · **Parent:** #191 PHASE-2.6 · **Refreshed:** 2026-08-22
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Final alignment of browser/perf/a11y gates with the new surfaces (spec decision 15):

- Page-budget measurement covers homepage, patient entry, staff login, one representative route per role group under the same per-page cap
- Lighthouse thresholds unchanged (perf 0.85 / a11y 0.90 / BP 0.90 / SEO 0.90), re-baselined against the resolved homepage
- axe coverage extended to consent sheet + homepage inside the existing serial e2e suite
- Auth-loop e2e guard/routing/post-login assertions completed for the new route structure
- Deployed-smoke stability: patient login route path + demo OTP banner copy byte-stable (decision 16) - verified explicitly

Acceptance criteria: see #205 body verbatim.

## Read-list (in order)

1. Spec decisions 15 + 16 in #191 - exact gate scope (~0.5K tokens)
2. `scripts/measure-pages.cjs` + CI workflow perf/a11y jobs - what runs where today (~2K)
3. Current auth-loop Playwright spec + its axe integration - assertion surface to extend (~2K)
4. Deployed live-smoke script (TEST-D brief `docs/agents/briefs/TEST-D-live-smoke.md`) - the literal path/banner assertions to keep stable (~1K)

## Do NOT read

- Prototype views (implementation tickets own them), backend modules beyond smoke contract, `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-22: lint, typecheck, frontend units 72 tests, measure-pages PASSED (3 channels / 1.5 MB cap). E2E needs local backend - run once pre-edit for starting truth.

## Done-verify (acceptance criteria → commands)

- Full harness per AGENTS.md: lint, typecheck, both unit suites, integration (local PG if reachable), e2e, migration-check, scan
- Gate proof: intentionally overweight fixture fails page budget once, then reverted
- Lighthouse job green at unchanged thresholds on resolved homepage; scores recorded as new baseline

## Session record (2026-08-23)

- Baseline re-run pre-edit: lint PASS, typecheck PASS, frontend units 436/436, measure-pages PASS (5 channels), backend units 651/654 (3 failures caused by a local uncommitted `config.py` edit flipping DEFAULT_APP_ENVIRONMENT to dev - proven by stash isolation; unrelated to this ticket). E2E baseline failed on the stale staff-entry 404 assertion this ticket replaces.
- Gate proof done: ~1.3 MB fixture CSS referenced from the homepage pushed `/` to 2012.6 KB -> gate FAILED (exit 1) once, then reverted and re-verified green.
- Lighthouse: thresholds untouched. Local runs are host-distorted (gate's fresh-profile Chrome observed FCP 3.9 s / TTFB 570 ms on localhost vs 1.0 s in a plain Playwright probe of the same build) - the CI job is the arbiter for the green-light record. In-scope fix applied anyway: `preload: false` on the Mukta next/font setup stops eight woff2 (~320 KB) racing the critical path (devtools-throttled TBT 740 -> 300 ms locally).
- axe: homepage + open consent sheet scans added; two latent violations fixed (FinalCtaBand sub-line contrast 4.34 -> 5.4; ProfileNudges card titles h4 -> h2 for heading order).
- Auth loop: staff guard now asserts a rendered /staff/login (200 + heading) with return-url; patient deep-link post-login landing already asserted end-to-end; staff post-login landing stays unit-level (staff-routing.test.ts) until Phase 5 staff auth.
- Byte stability: `/login` exact-path + `Demo OTP:` banner copy pinned in-suite (playwright.config.ts sets NEXT_PUBLIC_DEMO_MODE for the e2e dev server only).

## Handoff notes

- Per-route budget additions should already have landed incrementally in tickets 07/09/10 - this ticket verifies completeness and closes gaps, it does not re-implement them.
- The byte-stability check is a guard against accidental copy edits: assert literal strings in the suite, fail loudly on drift.
