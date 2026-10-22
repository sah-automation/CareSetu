# Brief - 683 Dashboard: section restyle and resilient per-section loading

**Ticket:** #683 · **Parent:** #673 · **Refreshed:** 2026-10-09
**Reading surface:** ~2.4K tokens (budget 10K) - within budget

## Scope

The dashboard's review-queue and open-cases sections are restyled to match the new design so the page reads as one coherent design. The page keeps loading gracefully: skeletons while reads are in flight, and a per-section fallback so a partial read failure never blanks the whole page.

## Acceptance criteria

- [ ] The review queue is restyled to match the other dashboard sections (card/badge idioms, spacing)
- [ ] The open-cases section is restyled consistently with the new design
- [ ] Loading shows skeletons rather than blank space
- [ ] A failed read degrades per section, never blanking the whole page
- [ ] Existing behaviour and tests are preserved; new assertions cover the skeleton and per-section fallback
- [ ] Every new string ships in both English and Hindi (parity preserved)
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. The dashboard `ReviewQueueCard` and `OpenCasesCard` regions - the sections being restyled. (~700 tokens)
2. The dashboard page load-status handling and the existing `FeeSummarySkeleton`/`FeeSummaryError`/`ErrorBanner` - the per-read status pattern to generalise into per-section fallbacks. (~500)
3. The skeleton and empty-state primitives used across the console. (~300)
4. The `doctorConsole` i18n namespace in both locales. (~300)
5. The dashboard test blocks. (~600)

## Do NOT read

- The backend.
- Other surfaces beyond the dashboard.
- `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-10-09 (134 files / 2157 tests passed).
- `npm run typecheck:frontend` - confirmed green 2026-10-09.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - restyle, skeleton and per-section fallback assertions.
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- **Per-section, not page-wide.** A failed read degrades its own section (skeleton/fallback) and must not blank the whole page (user story 19). Model the per-section status on the existing isolated fee read rather than a single page-wide `loadStatus`.
- **Restyle reuses tokens.** No design-token, typography or colour-system changes; compose the existing card/badge/skeleton idioms (spec out-of-scope list).
- **Existing tests are a contract.** Keep behavioral assertions; add skeleton/fallback assertions rather than rewriting them.
- **No em-dashes anywhere** (lint-gated) - use simple dashes.
