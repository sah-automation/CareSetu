# Brief - 679 Extract the shared health-background block

**Ticket:** #679 · **Parent:** #673 · **Refreshed:** 2026-10-09
**Reading surface:** ~2.1K tokens (budget 10K) - within budget

## Scope

Extract the doctor-side read-only health-background block currently inline on the patient-detail page into a shared presentational component: blood group plus the five chip areas (conditions, allergies, medications, immunizations, family history). It takes already-fetched data plus labels and performs no reads, keeping the existing not-shared, empty ("none recorded") and chip behaviour intact. The patient-detail page is refactored to render it with no behaviour change, so the case workspace History tab (ticket #682) can reuse it.

## Acceptance criteria

- [ ] A shared presentational health-background component renders blood group and the five chip areas, the empty ("none recorded") state and the not-shared state
- [ ] It takes already-fetched data plus labels; performs no API read
- [ ] The patient-detail page renders it; no behaviour change and existing patient-detail tests pass unchanged
- [ ] Component tests cover the populated, empty and not-shared states
- [ ] Labels are passed in (no new dictionary strings required); EN/HI parity preserved
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. The patient-detail page's `HealthBackgroundBlock` and `HealthRow` regions - the exact markup being extracted, including the blood-group row and the five chip areas. (~700 tokens)
2. `NotSharedCard` (title/body props, `locked-section` testid) - the not-shared state the block already routes a null section through. (~150)
3. `HealthBackground` and `HealthBackgroundView` in the doctor API client (`set`, `acknowledged`, `background`, plus `blood_group` and the five string arrays) - the data contract the component takes. (~250)
4. The `doctorPatients` i18n health labels in both locales - the field labels and the "none recorded" copy the block renders. (~400)
5. The patient-detail test blocks that assert the health-background section - these must keep passing unchanged after the extraction. (~600)

## Do NOT read

- The backend.
- The patient-owned `HealthBackgroundZone` / `HealthBackgroundSnapshotForm` - a different, authoring surface, not a read-only reuse target.
- The unrelated patient-detail sections (contact, consultation history, case workspace).

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-10-09 (134 files / 2157 tests passed).
- `npm run typecheck:frontend` - confirmed green 2026-10-09.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - the new component suite (populated, empty, not-shared) plus the unchanged patient-detail suite.
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- **"Not shared" and "none recorded" must stay visually different.** A locked section renders the calm not-shared card; a set-but-empty section renders the quiet "none recorded" state. Collapsing them would tell a doctor a patient has no allergies when the answer is unknown - that distinction is the whole point of the section.
- **Pure prefactor.** The patient-detail page must behave identically after this ticket; the only change there is import and wiring. Existing patient-detail assertions pass unchanged.
- **Labels travel in, not from a new namespace.** The component takes its labels as props so #682 can feed it the same strings; do not fork a new dictionary block.
- **No em-dashes anywhere** (lint-gated) - use simple dashes.
