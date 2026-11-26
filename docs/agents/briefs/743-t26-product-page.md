# Brief - #743 Product lens page

**Ticket:** #743 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Give the product manager a Product lens page: active users with stickiness and throughput, the funnel with its per-step completion and abandonment, and retention cohorts - one page, the existing panel frame, the existing chart primitives, the same wire contract the Business lens established.

- [ ] A Product destination renders panels for active users and throughput, the funnel, and retention cohorts.
- [ ] The funnel panel is filterable by outcome, and its success and abandonment figures are shown together rather than apart.
- [ ] The page proves its loading, empty, error and ready states by test id, using the shared stub-fetch helper the Business lens established.
- [ ] The wire contract is proven against the real client with a real operator token, including that quoted decimals arrive as numbers.
- [ ] Monthly active users are shown as computed in the system of record, never as a vendor-retention-truncated figure.
- [ ] Every new nav label resolves in both locales.

## Read-list (in order)

1. Spec #717 - the product-KPI user stories; Implementation Decisions 22, 23; Testing Decisions (the frontend page and wire seams). (~1K)
2. The Business lens page (#737) - the newest sibling and the shape to copy, including the shared stub-fetch helper's location and use. (~1.3K)
3. The operator observability panel page component and its panel frame - state test ids and the retry affordance. (~0.9K)
4. The observability client module: its fetch helpers, shape guards and decimal normalisation for the three new reads. (~1.1K)
5. The chart primitive module's bundle-boundary rule, plus the existing funnel-like and distribution charts for vocabulary. (~0.8K)
6. The dictionary's nav namespace and the bilingual parity test. (~0.5K)

## Do NOT read

- Backend sources - every read you consume exists (#740, #741, #742).
- The sidebar and nav configuration - #744 onward own the IA.
- The Reliability lens page's internals - a sibling, already built, and its patterns were copied here.
- `docs/archive/`, unrelated role shells.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- Three panels, three reads. Keep each panel's states tested; the empty state matters most here, because an empty funnel and an empty ledger look identical on screen and mean different things.
- The outcome filter is a panel-level control. Changing it re-reads; decide whether it lives in the URL so an operator can share the view they are looking at.
- Bilingual parity is a build gate - both locales before finishing, not after.
- This is the last lens page before the IA work. If the shared helper needed adjusting for this page's shape, change the helper, not the call site - three lenses must share one wire contract.
- #744 adds the destinations for all three lenses to the nav configuration. This ticket adds a route and a label; it does not restructure navigation.
