# Brief - 676 Dashboard: enriched open-case cards

**Ticket:** #676 · **Parent:** #673 · **Refreshed:** 2026-10-09
**Reading surface:** ~3.1K tokens (budget 10K) - within budget

## Scope

The dashboard's open-cases section switches from the unenriched open-cases read to the console's patient-enriched cases read (the same read the cases list uses), which returns the identical non-closed case set plus patient name, age, photo presence, stage, forced-review flag and updated-at. Each open case renders as the shared doctor card (avatar, name plus age, chip row, stage chip, meta line, whole-card link) - the same component the cases list and patients list use - so the dashboard and the cases list stay in step and whole-card focus/accessible-name behaviour is preserved. A case needing forced review shows the verify chip on its card.

## Acceptance criteria

- [ ] Dashboard open cases come from the patient-enriched console cases read, not the unenriched open-cases read
- [ ] Each open case renders via the shared doctor card: patient name plus age, stage chip, meta line and whole-card link
- [ ] A case needing forced review shows the verify chip on its card
- [ ] Updated-at renders as a relative "time ago" meta line
- [ ] The whole card is one focus stop and one link; the accessible name includes the patient
- [ ] Every new string ships in both English and Hindi (parity preserved)
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. The dashboard `OpenCasesCard` region and the page `load` plus `cases` state - the unenriched `CaseDetailView[]` feed being replaced. (~700 tokens)
2. `listDoctorCases`, `DoctorCaseRow` and `DoctorCasesListView` in the doctor API client - the enriched feed: `patient_name`, `patient_age`, `has_photo`, `stage`, `forced_review`, `updated_at`, and the boolean guard on `forced_review`. (~400)
3. The shared `DoctorListCard` props and anatomy (`DoctorListCardProps`, `DoctorCardChip`) and its existing adopters (the patients list row and the cases list grid) - the card to reuse and the accessible-name/whole-card-link contract. (~700)
4. `stageChipView` and `STAGE_CHIPS` in the stage-chip helper - how a stage maps to a chip label and tone. (~300)
5. The `doctorConsole` i18n namespace - `caseCardA11y`, the `stageX` labels and the `timeAgo*` copy. (~400)
6. The dashboard test blocks for open cases. (~600)

## Do NOT read

- The backend. The enriched projection is pinned by `DoctorCaseRow` and the console OpenAPI slice.
- The care `listOpenCases` internals - it loses this consumer.
- The unrelated dashboard sections (review queue, fee, greeting).

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-10-09 (134 files / 2157 tests passed).
- `npm run typecheck:frontend` - confirmed green 2026-10-09.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - open-case card assertions (name/age/stage/verify chip/whole-card link).
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- **No second copy of the non-closed filter.** Switching the feed source is deliberate: the dashboard must show exactly the cases the cases list shows. Do not keep a parallel `listOpenCases` feed.
- **`forced_review` is a guarded boolean.** A truthy `"false"` string must not pass; the client guard already enforces the type - do not coerce with `Boolean()`.
- **Reuse, do not fork, the card.** The dashboard, cases list and patients list must render the same `DoctorListCard`, and its single focus stop plus patient-inclusive accessible name are acceptance criteria (accessibility note in the spec).
- **Relative time** comes from the existing `timeAgo*` copy; do not add a date-format library.
- **No em-dashes anywhere** (lint-gated) - use simple dashes.
