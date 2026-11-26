# Brief - 15 End-to-end proof for the corrected surfaces

**Ticket:** #660 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

The corrected surfaces get proof that they render in the real app rather than only against mocked transports. The doctor workspace spec visits the cases grid and the patients grid and asserts both render and that a card navigates. The patient journey spec asserts the consent log shows a name rather than an id, and that the record entry page's labelled medicine block renders.

This ticket is thin by design. It asserts what the component suites cannot: that the real app serves these surfaces, that the real client sends them, and that the patient sees a human name. #624 is the reason - both page suites mock the transport wholesale, so a contract drift shipped green until a real user opened the page.

## Acceptance criteria

- [ ] The doctor workspace spec visits the cases list and the patients list and asserts both card grids render, and that a card navigates to its case / patient.
- [ ] The patient journey spec asserts the consent log shows a resolved name rather than an id.
- [ ] The patient journey spec visits the record entry page and asserts the labelled medicine block renders.
- [ ] Both specs keep their existing serial-mode flow and existing assertions green.
- [ ] No new Playwright test is added for a surface the spec deliberately leaves out.

## Read-list (in order)

1. The `#645` spec's "Why now" / "#624" paragraph and its testing bullet - the drift that reached production, and why real-app coverage is required rather than optional. (~400 tokens)
2. The doctor workspace end-to-end spec - its fixture seeding, its serial flow, the testid helpers it already has, and its existing assertions. ~5K is too much of the budget for one file, so read its helpers and its first navigation block, then grep for the remaining testid strings. (~2K)
3. The patient journey end-to-end spec - same treatment: its helpers, its serial flow, its existing consent-log assertions. (~2K)
4. The Playwright configuration - the projects, the serial-mode rationale, the web-server setup, and the base URL. (~400 tokens)
5. `tests/integration/README.md` - only to understand what the e2e run depends on, and whether a database is required. (~300 tokens)
6. The test ids the two specs will assert: the doctor grid families from #651/#652, and the consent-card / medicine-block ids the earlier tickets preserved. Grep, don't read files. (~400 tokens)

## Do NOT read

- `docs/archive/`.
- The frontend component source beyond the test ids the specs assert. You are writing assertions, not changing components. If an assertion fails because a test id is missing, that is a defect in the implementing ticket - report it, do not fix it here.
- The backend.
- The unit suites. Their green is a prerequisite, not your concern.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - expect **1 failed | 2024 passed**, the single pre-existing failure being `record/page.test.tsx > RecordPage access history > shows an empty state when there is no access history`. It fails on the untouched tree.
- `npm run test:unit:backend` - **currently green: 2867 passed.**
- `npm run typecheck` - **currently green.**
- `npm run test:e2e` - confirm the existing suite is green **before** you add anything, so a new failure is attributable to your assertion. Browsers come from the shared cache in `D:\Dev\tools\`.

#652, #654, and #656 must all have landed. Verify each before you start.

## Done-verify (acceptance criteria → commands)

- `npm run test:e2e` - the new assertions green, and both specs' pre-existing assertions still green.
- Then the **full gate set**, because this is the ticket that proves the whole correction:
  - `npm run test:unit:backend`
  - `npm run test:unit:frontend`
  - `npm run test:integration` - skips if PostgreSQL is unreachable; record which way it went.
  - `npm run test:e2e`
  - `npm run typecheck`
  - `npm run lint`
  - `npm run migration-check`
  - `npm run scan`

## Handoff notes

- **Serial mode is not an oversight.** The two specs run serially because they seed and mutate shared rows. Do not add `test.describe.configure({ mode: 'parallel' })` or split a spec in two to "speed it up" - you will trade a deterministic suite for flaky CI.
- **Assert on meaning, not on markup.** "Shows a name rather than an id" is a real assertion only if it checks the human string and - better - asserts the raw counterparty id is _absent_ from the rendered text. Asserting `toBeVisible()` on a container that happens to contain the id proves nothing. This is the whole point of the ticket.
- **A missing test id is an upstream defect, not yours.** The earlier tickets preserved every id precisely so this spec could select them. If you must add a selector to make an assertion possible, stop and report: it means an implementing ticket dropped something it promised to preserve.
- **The seeded names must be realistic.** If your fixture creates a counterparty whose resolved name is `"Test Doctor"`, the assertion passes while proving nothing about real resolution. Seed a name the backend actually resolves, so the test exercises the seam rather than a hardcoded fallback.
- **The medicine block assertion should check labels, not just presence.** "The labelled medicine block renders" means a `Dose` / `Frequency` / `Duration` label is visible - not merely that some text appeared where medicines go. That is the regression #656 prevents.
- **Navigation assertions need a settle.** A grid that renders and a card link that navigates are two different waits. Follow the existing specs' waiting convention rather than inventing one.
- **You are the last real-app check before #661.** If something renders only under a mocked transport, this is where it surfaces.
