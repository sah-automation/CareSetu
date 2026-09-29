# Brief - #515 Professional prescription cards on /patient/record

**Ticket:** #515 · **Parent:** #512 · **Refreshed:** 2026-09-23
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Prescription cards on the My Record timeline (`/patient/record`) become professional: the medicine name leads as the title, a dose line (`5 mg · once daily · 30 tablets`), an attribution line `issued by <doctor> · <date>`, a chemist line only when the payload carries one, "+N more" for multi-item prescriptions, and the issued tag becomes `Active` (success tone) with `Delivered` unchanged. Pre-enrichment entries whose payload has no `items` degrade honestly to today's lean `Rx #<id> · <date>` form. The single view-model seam (`describeEntry`) is the shaping point; consultation/lab/metric/settlement cards keep their existing anatomy.

Acceptance criteria (from the ticket):

- [ ] `describeEntry` shapes an enriched prescription payload into: medicine-name title, dose line, `issued by <doctor>` attribution, and renders neutral copy when `attributed_doctor_name` is null.
- [ ] Delivered payload with a chemist value renders the chemist line (render-if-present, absent when not carried).
- [ ] Multi-item prescription shows `+N more` (translated in Hindi).
- [ ] Issued state badge reads `Active` with the success tone; `Delivered` unchanged. Dictionaries gain the new EN/HI keys (`record.badge.active`, issued/prescribed by, `+N more`, neutral attribution) and `EntryCardStrings` extends accordingly.
- [ ] Legacy payload without `items` degrades to the lean `Rx #<id> · date` subtitle (same as today); unit tests cover both shapes, plus record-page composition tests on rendered copy/pills.

## Read-list (in order)

1. `describeEntry` + `EntryCard` + the defensive payload helpers (`payloadString`/`payloadNumber`, and the lab `entryFlagRows` parser as the imitative defensive-parse style) - the prescription branch is the code that changes (~1.5K).
2. The timeline view-model tests - existing prescription card prior art (`Rx #9` delivered and `Rx #12` issued cases) to mirror and extend (~1.5K).
3. The record page card renderer `renderEntry` (title, badge pill via `BADGE_TONE`, subtitle, lab flags) and its page test - composition assertions only (~1.5K).
4. The EN/HI dictionaries `record.badge.*` section and `EntryCardStrings` keys, plus the dictionary parity-gate test (EN/HI shape equality auto-covers the new keys) (~1K).
5. Parent spec #512 "Record entry payload contract" + "Tags (D2)" + "Frontend shaping" - the exact `items`/`attributed_doctor_name` shapes and the Active-tone decision (~0.5K).

## Do NOT read

- Backend modules, `RecentActivityCard`, the entry-detail page internals, `prototype/`, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run typecheck:frontend` - verified green 2026-09-23.
- Targeted: `npm run test -w @caresetu/frontend -- "src/lib/record/timelineView.test.ts" "src/app/(patient)/patient/record/page.test.tsx"` - verified 132 relevant tests pass across the four record/home files. The full `npm run test:unit:frontend` suite can flake on JSDA worker-spawn timeouts under load on this machine (2 timeout + 4 pool-spawn errors on 2026-09-23, all in unrelated files) - re-run the targeted files, which are green.

## Done-verify (acceptance criteria → commands)

- The two targeted frontend files above, plus the view-model/dictionary unit suite.
- `npm run typecheck:frontend`.

## Handoff notes

- `describeEntry` is the single shaping seam - the record card, Recent activity, the health-snapshot tile, and the entry-detail header all render through it. Upgrade it once; the other surfaces inherit (their tickets update composition tests only).
- New defensive helpers parse `items` (array, per-row `typeof` guards, `name` always a non-empty string, `dose`/`frequency`/`duration` nullable) and `attributed_doctor_name` in the `entryFlagRows` style; `isDeliveredPrescription` stays the delivered rule.
- Badge: issued -> `t.badge.active` (new key) with the **success** tone (was warm); delivered stays `t.badge.delivered` + success. Pure dictionary + mapping change.
- Multi-item card: title = first item's `name`, subtitle carries that item's dose line + `issued by <doctor> · <date>`, and a "+N more" indicator when `items.length > 1`; legacy (no `items`) keeps title `t.badge.prescription` and the `Rx #<id> · date` subtitle.
- Neutral attribution copy (fallback when `attributed_doctor_name` is null) is a new dictionary string, EN + HI.
- Tests assert rendered external behavior (title/subtitle/badge copy), never helper internals.
