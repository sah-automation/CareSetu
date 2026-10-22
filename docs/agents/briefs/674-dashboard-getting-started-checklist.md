# Brief - 674 Dashboard: getting-started checklist for new doctors

**Ticket:** #674 · **Parent:** #673 · **Refreshed:** 2026-10-09
**Reading surface:** ~1.6K tokens (budget 10K) - within budget

## Scope

For a brand-new doctor with no open cases and an empty review queue, the dashboard shows a getting-started checklist instead of sitting near-empty. Each step shows whether it is done or pending and links to where the doctor completes it. The checklist is absent for a doctor who already has cases.

## Acceptance criteria

- [ ] The checklist appears when the doctor has no open cases and an empty review queue, and is absent otherwise
- [ ] Each step renders a done/pending state
- [ ] Each step links to where the doctor completes it
- [ ] Every new string ships in both English and Hindi (parity preserved)
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. The dashboard page `load` and state - the open-cases and review-queue data that drives the empty-versus-populated condition. (~400 tokens)
2. The dashboard test blocks - the fixtures to extend for empty versus populated doctors. (~600)
3. The `doctorConsole` i18n namespace plus the doctor profile-completeness hints - the reused notion of a "done" step and where a step links. (~400)
4. The card and badge idioms used elsewhere on the dashboard. (~300)

## Do NOT read

- The backend.
- The unrelated dashboard sections (KPI row, greeting, profile-status card).
- `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-10-09 (134 files / 2157 tests passed).
- `npm run typecheck:frontend` - confirmed green 2026-10-09.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - checklist present/absent and step-state assertions.
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- **Absence is the interesting case.** The checklist appears only for a doctor with no open cases and an empty review queue; a doctor with either must not see it. Assert both directions.
- **Steps mirror the profile-completeness hints.** Reuse the same "done" notions the profile-status card uses (verified, fee, about, clinic name) so the two surfaces agree on what "complete" means, but keep the links pointing at where the doctor completes each step.
- **No em-dashes anywhere** (lint-gated) - use simple dashes.
