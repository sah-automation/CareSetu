# Brief - 547 Doctor review screens restyle

**Ticket:** #547 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~4.5K tokens (budget 10K) - within budget

## Scope

The doctor review screens (the Pre-summary review/finalize surface and any review-queue read surface the doctor uses) are rebuilt visually to the patient shell's design language, preserving data fetching, state logic, endpoints and tests (US-30, US-32). Visual only. All copy EN/HI.

AC:

- [ ] Doctor review screens restyled to the patient-shell visual language (cards, status chips, spacing, loading/empty states)
- [ ] Existing behavior and tests unchanged
- [ ] Desktop and mobile verified; EN/HI parity
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The doctor review screen `app/(doctor)/doctor/review/[intakeId]/page.tsx` + its test - the review/finalize surface to restyle (fetch/reviewPreSummary/markConsultComplete flow preserved) (~1.8K).
2. Any review-queue read surface the doctor uses (`fetchReviewQueue` consumers on the landing/queue) - restyle without touching the data reads (~0.8K).
3. The patient-shell visual language: card/chip/skeleton/empty-state primitives (~1K).
4. The i18n `doctorConsole` + `caseWorkspace` dictionary blocks + parity test (~0.5K).

## Do NOT read

- Backend code, the case workspace surface (#546 owns it), the cases list (#545 owns it), `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-09-24 (1288 passed, 89 files).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - review-screen tests still green (behavior preserved) + presentational assertions.
- `npm run typecheck` - clean.

## Handoff notes

- Visual-only: data fetching, state logic, endpoints, and tests are the contract - existing tests pass unchanged.
- One-action finalize and the async care-case birth re-poll behavior must remain untouched; restyle only their presentation.
- Keep the chip/card treatment consistent with #545/#546 so the three doctor surfaces read as one design language.
- No em-dashes anywhere (lint-gated); use simple dashes.
