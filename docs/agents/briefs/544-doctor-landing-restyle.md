# Brief - 544 Doctor landing completion + restyle

**Ticket:** #544 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~3.5K tokens (budget 10K) - within budget

## Scope

The doctor landing reads as a finished console: the coming-soon Patients/Profile cards are replaced with real entry cards, and a compact consultation-fee summary card shows the fee and links into the Profile (the fee editor itself now lives there, per the doctor profile ticket) (US-7, US-27). The landing is also restyled to the patient shell's design language - cards, status chips, spacing, loading/empty states - on desktop and mobile, without changing its data fetching or logic. All copy EN/HI.

AC:

- [ ] Landing coming-soon cards are gone; Patients and Profile entry cards deep-link to their live pages
- [ ] The fee summary card renders the current fee and links to the Profile editor
- [ ] Landing matches the patient-shell visual language (cards, chips, spacing, loading/empty states) on desktop and mobile; existing landing behavior/tests preserved
- [ ] EN/HI parity; component tests + `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The doctor landing `app/(doctor)/doctor/page.tsx` + its test - the hardcoded coming-soon Patients/Profile cards (testids `coming-soon-patients`/`coming-soon-profile`), the fee editor block being moved out, and the review-queue/cases/fee data reads to preserve (~1.5K).
2. The patients + profile page routes from #541/#543 (live destinations the entry cards deep-link to) and the profile page's fee editor (the fee summary's target) (~0.5K).
3. The patient-shell visual language: `EmptyState`, `ErrorBanner`, `Skeleton`, card/chip patterns from the patient home (`components/patient/home`) (~1K).
4. The i18n `doctorConsole` block + parity test for new copy (~0.5K).

## Do NOT read

- Backend code, case-workspace internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-09-24 (1288 passed, 89 files).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - landing tests for entry cards, fee summary link, and preserved data behavior green.
- `npm run typecheck` - clean.

## Handoff notes

- Requires #541 (Patients page) + #543 (Profile page) landed - the entry cards and fee summary cannot deep-link until those routes live.
- Remove the landing's hardcoded coming-soon cards; keep the data fetching/logic (`fetchReviewQueue`, `listOpenCases`, fee read) untouched - this is a presentational pass.
- The fee editor leaves the landing; only a read-only summary card pointing into the Profile stays.
- No em-dashes anywhere (lint-gated); use simple dashes.
