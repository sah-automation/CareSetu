# Brief - 546 Doctor case workspace + Pre-summary restyle

**Ticket:** #546 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~5.5K tokens (budget 10K) - within budget

## Scope

The case workspace - inner tabs, the Pre-summary view, and the prescription gate (including the verification-declaration step) - is rebuilt visually to the patient shell's design language (cards, status chips, spacing, typography, loading/empty states) with every existing behavior preserved: data fetching, state logic, endpoints, existing tests, and the case-workspace mobile behavior (US-30, US-31, US-32). This is visual only - the prescription approval gate logic and idempotency are untouched. All copy EN/HI.

AC:

- [ ] Case workspace (inner tabs, Pre-summary, prescription gate incl. verification declaration) restyled to the patient-shell visual language
- [ ] Prescription gate behavior/mobile behavior unchanged; existing workspace tests still pass
- [ ] Desktop and mobile verified; EN/HI parity
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The case workspace `app/(doctor)/doctor/cases/[caseId]/page.tsx` - the load slice, handler slice, and the approve-gate/verification-declaration UI slice (the restyle targets; the declaration checkbox block and its guard must render identically) (~2.5K).
2. The existing workspace test `[caseId]/page.test.tsx` - the behavior assertions (incl. declaration-gate cases) that must keep passing unchanged (~1.5K, relevant cases only).
3. The patient-shell visual language: card/chip/skeleton/empty-state primitives and tone classes (~1K).
4. The i18n `caseWorkspace` + `doctorConsole` blocks + parity test (~0.5K).

## Do NOT read

- Backend code, the review screens (#547 owns them), the cases list (#545 owns it), `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-09-24 (1288 passed, 89 files).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - workspace page tests still green (behavior preserved) + desktop/mobile presentational assertions.
- `npm run typecheck` - clean.

## Handoff notes

- The prescription approval gate and idempotency are the hard contract: the verification-declaration checkbox gating `approvePrescription` must remain functionally identical, only visually restyled.
- Existing tests passing unchanged is an acceptance criterion, not a side effect: do not rename testids/handlers unless updating the test file is the only way - and then keep the behavioral assertion, not the markup, as the contract.
- Mobile behavior (the workspace's tab/navigation on phones) is preserved.
- Coordinate the chip treatment with #545/#547 so the doctor console reads as one design language.
- No em-dashes anywhere (lint-gated); use simple dashes.
