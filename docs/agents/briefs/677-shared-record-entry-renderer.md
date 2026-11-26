# Brief - 677 Shared record-entry renderer for consultation history

**Ticket:** #677 · **Parent:** #673 · **Refreshed:** 2026-10-09
**Reading surface:** ~2.8K tokens (budget 10K) - within budget

## Scope

A single presentational component that renders one consultation-history record entry - its type tag and date, plus the full detail of its payload. Both the patient-detail consultation history and the case workspace History tab consume it, replacing their two near-duplicate tag-only inline markups. Per entry type it renders: `prescription` (status, one line per medicine with name, dose, frequency and duration, plus the attributed doctor), `lab_report` (file name and order reference), `settlement` (amount formatted from paise and order reference); `consultation`, `metric`, and any unknown or empty payload fall back to the type tag plus date only. It takes already-fetched data and label strings; it performs no reads and introduces no production seam.

## Acceptance criteria

- [ ] Renders the type tag and date for every entry, with per-type detail for `prescription` (medicine lines plus attributed doctor), `lab_report` (file plus order) and `settlement` (amount plus order)
- [ ] Falls back cleanly to type-tag-plus-date for `consultation`, `metric`, unknown and empty payloads; never breaks and never looks empty by accident
- [ ] Prescription medicine lines show name, dose, frequency and duration; no medicine field is silently dropped
- [ ] The settlement amount is formatted from paise using the existing currency-formatting idiom
- [ ] Purely presentational - takes already-fetched data and labels; performs no API read
- [ ] Component tests cover each payload type and the empty and unknown fallbacks
- [ ] Every new string ships in both English and Hindi (parity preserved)
- [ ] `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` pass

## Read-list (in order)

1. `RecordEntryView`, `RecordTimeline` and `RecordEntryType` in the record API client - the entry shape and the `payload: Record<string, unknown>` bag the renderer interprets per type. The payload is loosely typed, so every field is read defensively. (~300 tokens)
2. The two tag+date markups being replaced - patient-detail `ConsultationHistoryBlock` and case-workspace `ConsentedHistory`'s entry list item - together with their `entryTypeLabel`/`entryBadgeLabel` and `historyDate`/`formatHistoryDate` helpers, which must converge on one rendering. (~700)
3. The `record.badge` i18n namespace in both locales - the existing type-tag labels (`consultation`, `prescription`, `labReport`, `metric`, `settlement`). (~300)
4. The doctor-console OpenAPI fixture (`openapi-doctor-console.json`) and `DoctorPatientDetailView.consultation_history` - the concrete payload field names for prescription (items plus attributed doctor), lab_report (file plus order) and settlement (amount in paise plus order). Match these names exactly; do not invent fields. (~800)
5. The paise-formatting helper `formatFeePaise` exported by the pick card - the existing currency idiom to reuse for the settlement amount. (~150)
6. `ConsentedHistory.test.tsx` as prior art for the shared history component's test shape. (~500)

## Do NOT read

- The backend. The wire shape is pinned by the OpenAPI fixture above.
- The two pages beyond the markup blocks named in item 2.
- `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-10-09 (134 files / 2157 tests passed).
- `npm run typecheck:frontend` - confirmed green 2026-10-09.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - the new component suite covers each payload type plus empty/unknown fallbacks.
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- **`payload` is a bag, not a typed object.** Read each field defensively and fall back to type-tag-plus-date whenever a field is absent - an unknown or empty payload must never crash or render a half card.
- **Match the projection's field names.** Grep the payload fields out of the OpenAPI fixture; a guess at a field name renders nothing and looks like an empty payload. The fixture is the contract.
- **Keep the scan line.** Every entry keeps its type tag and date alongside whatever detail renders (user story 24); the date helper is shared with the surfaces you are replacing.
- **Presentational only.** No fetch, no hook, no state beyond rendering. This is why no production seam is introduced.
- **Every new string in both locales.** English and Hindi dictionaries both, preserving parity.
- **No em-dashes anywhere** (lint-gated) - use simple dashes in code comments and copy.
