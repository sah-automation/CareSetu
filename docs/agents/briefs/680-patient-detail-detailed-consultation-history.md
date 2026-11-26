# Brief - 680 Patient detail: detailed consultation-history rendering

**Ticket:** #680 · **Parent:** #673 · **Refreshed:** 2026-10-09
**Reading surface:** ~2.3K tokens (budget 10K) - within budget

## Scope

The patient-detail page's Consultation history renders the full content of each entry via the shared record-entry renderer (#677) instead of a bare tag and date: prescription medicines plus the attributed doctor, lab-report file plus order, settlement amount plus order, with a clean fallback for entries that carry no payload. Every entry keeps its type tag and date. Consent gating on the `consultations` scope is unchanged - a denied section stays the calm not-shared state and an empty section stays the quiet empty state, never an error.

## Acceptance criteria

- [ ] Each consultation-history entry renders its per-type detail via the shared record-entry renderer, keeping its type tag and date
- [ ] Entries with no detailed payload still render cleanly with type plus date
- [ ] The rendered content is identical to the case workspace History tab (same renderer, same source projection)
- [ ] A denied section renders the not-shared card; an empty section renders the quiet empty state; never an error
- [ ] Existing patient-detail test hooks are preserved and new assertions cover the per-type detail
- [ ] Every new string ships in both English and Hindi (parity preserved)
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. The shared record-entry renderer's props and interface (from #677) - what the patient-detail page must pass it. (~300 tokens)
2. The patient-detail `ConsultationHistoryBlock` and its `Lookup` - the block being rewritten, its current not-shared/empty branches and its date helper. (~600)
3. The patient-detail page test suite - the consultation-history blocks you must keep green and extend. (~700)
4. The `record.badge` and `doctorPatients` i18n namespaces in both locales - the tag labels and the empty/not-shared copy. (~400)
5. `NotSharedCard` - the not-shared state. (~150)

## Do NOT read

- The backend. `DoctorPatientDetailView.consultation_history` already carries the payloads.
- The case workspace. The shared renderer is the coupling; do not copy its wiring.
- The shared health-background block (#679) - a separate section on the same page.
- `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-10-09 (134 files / 2157 tests passed).
- `npm run typecheck:frontend` - confirmed green 2026-10-09.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - the patient-detail suite asserts per-type detail plus the preserved not-shared/empty states.
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- **One read, one renderer.** The patient-detail page and the case workspace History tab must render identical history content (user story 33). You achieve that by both consuming the shared renderer over `DoctorPatientDetailView.consultation_history` - do not fork a second renderer or re-shape the data.
- **The not-shared and empty branches are contracts.** A `null` history renders `NotSharedCard`; an empty `entries` array renders the quiet empty card. Only the populated branch changes to the shared renderer.
- **Preserve test hooks** and add detail assertions rather than rewriting meaningful behavior assertions.
- **No em-dashes anywhere** (lint-gated) - use simple dashes.
