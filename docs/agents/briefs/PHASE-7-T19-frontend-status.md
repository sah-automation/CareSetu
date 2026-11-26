# Brief - T19 Frontend: intake status list page

**Ticket:** #363 · **Parent:** #344 · **Refreshed:** 2026-09-08
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

A patient can see where each submission stands without pestering anyone: the intake-status view with the four statuses Captured / Structuring / Ready for Review / Recapture needed, a refresh of statuses from the backend, and a continue affordance from a ready pre-summary into consultation booking. Bilingual per prototype.

Acceptance criteria:

- [ ] The status list renders the four intake statuses, mapped from the backend status values
- [ ] Statuses refresh from the backend (get_intake/get_pre_summary) in page
- [ ] A ready pre-summary offers the continuation into consultation booking
- [ ] Bilingual copy passes the i18n parity test

## Read-list (in order)

1. `prototype/phase-7-8/patient-case-status.html` + `prototype/phase-7-8/BUILD-PLAN.md` (status surface part) - the four statuses and copy (~2K)
2. The intake client from T15 - get_intake/get_pre_summary status values + DTOs (~1.5K)
3. `apps/frontend/src/lib/i18n/dictionaries.ts` + `dictionaries.test.ts` - bilingual strings and parity gate (~2K)

## Do NOT read

- `docs/archive`
- backend internals beyond the route contract
- doctor-side surfaces (Phase 8)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 687 pass with 1 known unrelated flake: `(operator)/operator/verification/[partner_id] > renders partner profile on load` times out intermittently (verified 2026-09-08); re-run if only that test fails
- `npm run typecheck` - clean (verified 2026-09-08)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`
- `npm run check:pages`

## Handoff notes

- Four statuses map 1:1 onto the backend machine status values from T02: Captured / Structuring / Ready for Review / Recapture needed (Recapture needed surfaces the re-record/forced-text path).
- Continue affordance appears only when the pre-summary is ready (Ready for Review), leading into consultation booking (Phase 8 boundary).
