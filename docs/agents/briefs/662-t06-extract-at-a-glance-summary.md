# Brief - 06 Extract the rail At a glance summary into a shared patient component

**Ticket:** #666 · **Parent:** #662 · **Refreshed:** 2026-10-08
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

The record page's rail "At a glance" summary is extracted from the page into a shared patient component that takes timeline-derived counts as input (presentational, fetches nothing), and the record page renders it with every existing test hook preserved. Pure prefactor: rendered behavior is identical, and the component is ready for the homepage to compose in ticket #671.

Acceptance criteria:

- [ ] A shared patient summary component renders the rail "At a glance" section from passed-in counts
- [ ] The record page uses it; the rail summary test hooks (rail testid, summary testid, footnote) still resolve
- [ ] No behavior or copy change on the record page - existing record page tests pass unchanged except for import/wiring updates
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. Spec #662 §Solution "Homepage rail parity" - the extraction decisions bullets (presentational summary taking timeline-derived counts) and user stories 26, 34-35 (~1.5K)
2. The patient record page (apps/frontend/src/app/(patient)/patient/record/page.tsx) - the rail aside shell, the inline "At a glance" section with its testids and footnote, and the count memos (`countByType`, issued-prescription count, flagged values) that feed it (~2.5K)
3. Record page test blocks for the zones/summary/rail footnote (apps/frontend/src/app/(patient)/patient/record/page.test.tsx) - the hooks the extraction must preserve (~1.5K)
4. `HealthSnapshotCard` (apps/frontend/src/components/patient/home/HealthSnapshotCard.tsx) - the precedent: a card already shared between the record page and homepage, showing where shared patient components live and how they are imported (~1K, skim for placement/import style only)

## Do NOT read

- The access-history accordion region of the record page (ticket #669)
- Homepage page shell (ticket #671)
- Backend; timeline group rendering (ticket #667); i18n dictionary beyond the keys the section already uses
- `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 2148 passed (2026-10-08)
- `npm run lint`, `npm run typecheck` - passed

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - record page suite green, all summary/rail hooks resolve
- `npm run lint`, `npm run typecheck`

## Handoff notes

- Presentational contract: counts go IN as props - the component must not fetch or re-derive counts (ticket #671 feeds it from a single shared own-record fetch; the record page passes its already-loaded timeline's counts).
- Preserve `record-rail`, `record-rail-summary`, and the footnote testid exactly.
- Placement: follow the shared-component precedent under `apps/frontend/src/components/patient/` (the HealthSnapshotCard import shows the accepted direction).
- Ticket #669 is blocked on this one (same page file); ticket #667 (timeline spacing) touches a different region and is independent.
