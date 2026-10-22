# Brief - #737 Business lens page

**Ticket:** #737 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Give the operator a Business lens page: one page whose panels answer whether this spend is healthy, where it goes, what a unit of value costs and who is heavy. It reads the same client, the same panel frame and the same chart primitives as the existing panels, so the console looks like one product rather than a growing pile of pages. This ticket also promotes the stub-fetch helper out of a single page test into a shared test helper, so every new lens page shares one wire contract.

- [ ] A Business destination renders its panels from the business read, using the existing panel frame and chart primitives - no direct chart-library import.
- [ ] The page proves its loading, empty, error and ready states by test id, including the retry affordance, exactly as the existing panels do.
- [ ] The wire contract is proven by stubbing fetch, keeping the real client, placing a real operator token in the session store, and asserting that quoted decimals arrive as numbers.
- [ ] The stub-fetch helper moves into a shared test helper used by every lens page test.
- [ ] Panels deep-link onward to the underlying AI traces where a trace identifier is available.
- [ ] Every new nav label resolves in both locales.

## Read-list (in order)

1. Spec #717 - the Business user stories; Implementation Decisions 27 and 34; Testing Decisions (the frontend wire seam and the page seam). (~1K)
2. The operator observability panel page component and its panel frame - the single owner of loading, error, empty and ready states, and the test ids it exposes. (~1K)
3. One existing panel page **end to end** - route, component, panel usage, page test and wire test - as the shape to copy. (~2K)
4. The chart primitive module and its bundle-boundary rule: panels import named re-exports from it and never the chart library directly. A page-check script enforces this. (~0.9K)
5. The read hook's load-status contract and its ref-held load, so the read fires once per mount. (~0.6K)
6. The observability client module: its shape guards, its decimal normalisation (`wireDecimal` and the decimal-field lists) and its fetch helpers. (~1.2K)
7. The dictionary's nav namespace and the bilingual parity test, for the new labels. (~0.7K)

## Do NOT read

- Backend sources - the read you consume already exists (#731, #732).
- The sidebar and nav configuration - #744 onward own the IA; this ticket adds a label, not a destination structure.
- The Reliability and Product lens pages - they are siblings built later against the shared helper this ticket creates.
- `docs/archive/`, unrelated role shells.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`
- `npm run typecheck`
- `npm run lint`
- `npm run check:pages` (the bundle-boundary page check, if the panels add routes)

## Handoff notes

- **The shared helper is the load-bearing part of this ticket.** Two lenses will follow (#738, #743) and a third wave will reuse it (#731's siblings). Move the stub fetch and JSON response helpers out of whichever page test declares them locally and give them a home every lens page test imports.
- Quoted decimals arriving as numbers is a real assertion, not a formality: the backend serialises `Decimal` as a JSON string and the client must parse it. A test that passes without asserting the conversion will not catch a regression there.
- Test ids are the contract for the state assertions. Use the panel frame's existing id convention rather than inventing parallel ones.
- Deep links here use the widened shape from #736. If #736 has not landed, the page can ship without the deep-link affordance and #736 or #738 adds it - but say which in the ticket comment, so it does not get lost.
- Bilingual parity is a build gate: a missing key in either locale fails the build. Add both before finishing.
