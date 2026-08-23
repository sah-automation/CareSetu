# Brief - T09 Resolved ten-section homepage & public chrome

**Ticket:** #200 · **Parent:** #191 PHASE-2.6 · **Refreshed:** 2026-08-22
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Server-rendered replacement of the marketing placeholder implementing the ten ordered sections: sticky header; hero + directory search with provider-type select, free-text, location chip defaulting to Daltonganj; specialty chips; category tiles; featured doctor cards; how-it-works explainer; trust/consent strip; providers band; final CTA band; four-column footer with discreet operator link.

Rules baked in: categories are marketing navigation over specialties - copy must not promise disease-based programs (gap G1). Featured cards call the future public directory endpoint behind a marked integration point and render the graceful "Directory launching soon in Daltonganj" empty state today (gap G2). Header carries wordmark, anchors, EN/Hindi toggle, session-aware auth button reading truthfully from root context. Below-fold media lazy-loads; homepage joins the measured routes in the page-budget script; public copy flows through the i18n engine at equal quality in both locales.

Acceptance criteria: see #200 body verbatim.

## Read-list (in order)

1. Prototype `home-resolved.html` - binding layout/copy source for all ten sections (~2.5K tokens)
2. PRD §4.x public-face feature sections - acceptance rules + G1/G2 gap constraints (~2K)
3. UI blueprint homepage IA section - section ordering rationale + header anatomy (~1.5K)
4. Ticket 03 dictionary/LangContext API - how public copy consumes translations (~0.5K)
5. Current placeholder `app/page.tsx` + `scripts/measure-pages.cjs` CHANNELS array - what gets replaced, where `/` gets added (~1.5K)

## Do NOT read

- Shell/split-auth/profile prototype views, backend directory work (none exists - integration point only), `docs/archive/`, e2e specs.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-22: lint, typecheck, frontend units 72 tests, measure-pages PASSED. Note: today's placeholder homepage is the Lighthouse gate target (`scripts/lighthouse-gate.cjs` measures `/`; thresholds perf 0.85 / a11y 0.90 / BP 0.90 / SEO 0.90) - keep those thresholds holding through the redesign; re-baselining is ticket 14's job.

## Done-verify (acceptance criteria → commands)

- Baseline set + new homepage component suites (ten sections present/order; mocked-fetch live-cards vs empty state; toggle parity)
- Extended `measure-pages.cjs` includes `/`, still passing
- Grep check: no disease-program promise strings in homepage copy

## Handoff notes

- Providers-band CTAs must carry the application-type preset (query param consumed by ticket 11's wizard route) - land the hrefs now even though the target route arrives with ticket 11.
- The featured-cards integration point: one marked client function returning typed provider cards; empty state when it yields none. Do not invent an API route.
- Footer operator link is discreet (low-emphasis) per prototype.
