# Brief - 545 Doctor cases list restyle

**Ticket:** #545 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~3.5K tokens (budget 10K) - within budget

## Scope

The doctor cases list looks designed - cards, status chips, spacing, loading and empty states - in the same design language as the patient shell, on desktop and mobile, without changing its data fetching, state logic, or tests (US-30, US-32). All copy EN/HI.

AC:

- [ ] Cases list is restyled to the patient-shell visual language (cards, status chips, spacing, loading/empty states)
- [ ] Existing data fetching and behavior are unchanged; existing page tests still pass
- [ ] Desktop and mobile layouts verified; EN/HI parity
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The doctor cases list `app/(doctor)/doctor/cases/page.tsx` + its test - the current markup to restyle (stage chips, list rows, links to the workspace) without touching loading/state logic (~1K).
2. The patient-shell visual language: `EmptyState`, `Skeleton`, chip/card class trios from the patient home (`_bg-soft/text-` tone classes, card surfaces) (~1K).
3. The i18n `doctorConsole` block + parity test for any copy touched (~0.5K).

## Do NOT read

- Backend code, case-workspace detail screens (#546 owns the workspace), the doctor landing, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-09-24 (1288 passed, 89 files).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - cases-list page tests still green (plus any new presentational assertions).
- `npm run typecheck` - clean.

## Handoff notes

- Visual-only: data fetching, state logic, endpoints, and existing tests are the contract - leave them untouched so the tests keep passing as-is.
- No shared `StatusChip` component exists today (chips are inline tone spans); either reuse the class trios or introduce the chip primitive here consistently with #546/#547.
- No em-dashes anywhere (lint-gated); use simple dashes.
