# Brief - #738 Reliability lens page

**Ticket:** #738 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Give the operator a Reliability lens page: the degraded-provider board, the live error stream, throughput and error rate with an honest concurrency story, queue depth and age, and an alert feed that can be acknowledged. One page, the existing panel frame, the existing chart primitives.

- [ ] A Reliability destination renders panels for the provider board, the live error feed, throughput and error rate, queue depth and age, and the alert feed.
- [ ] The error feed pages, collapses repeats with occurrence counts, and filters by open and resolved.
- [ ] An operator can acknowledge an alert from the page, and the acknowledged alert moves out of the open list.
- [ ] The concurrency panel reports recent activity and links out to the tracing backend's true gauge, so it is never presented as simultaneous concurrency.
- [ ] The page proves its loading, empty, error and ready states by test id, using the shared stub-fetch helper the Business lens established.
- [ ] Deep links are rendered per panel, and an unconfigured vendor renders as absent rather than broken.

## Read-list (in order)

1. Spec #717 - the reliability user stories; Implementation Decisions 17, 19, 21; Testing Decisions (the frontend page seam). (~1.2K)
2. The operator observability panel page component and its panel frame, including the state test ids and the retry affordance. (~0.9K)
3. The Business lens page (#737) - the newest sibling and the shape to copy, including how it uses the shared wire-test helper. (~1.2K)
4. The observability client module: its fetch helpers, shape guards and decimal normalisation, so the new reads are wired the same way. (~1.2K)
5. The alert feed component and the acknowledgement write it must now perform, including how it re-reads after a write. (~0.9K)
6. The chart primitive module's bundle-boundary rule, plus the existing health and quality charts as vocabulary for percentile and status rendering. (~0.9K)
7. The dictionary's nav namespace and the bilingual parity test. (~0.5K)

## Do NOT read

- Backend sources - every read you consume exists (#727, #728, #729, #730, #734, #735, #736).
- The sidebar and nav configuration - #744 onward own the IA.
- The Product lens page - a sibling built later.
- `docs/archive/`, unrelated role shells.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- This page has more panels than either sibling. If it exceeds budget in practice, split the panel set across two tickets rather than shipping a page with untested panels.
- The acknowledge action is a **write** on a page whose other panels are reads. Decide what happens to the alert feed after a successful acknowledgement - the acknowledged alert must leave the open list, and the test must assert it.
- "Recent activity", not "concurrency", in the panel title and in any copy that describes it. The link out to the tracing backend's gauge is the honest completion of that panel.
- Deep links per panel come from #736's widened response. An unconfigured vendor renders as absent - the existing behaviour, which this page must not regress into a visible placeholder.
- Use the shared stub-fetch helper #737 created. If you find yourself redeclaring `stubFetch` or `jsonResponse` locally, that helper did not land properly.
