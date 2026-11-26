# Brief - 11 Record entry medicines as labelled blocks

**Ticket:** #656 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~4K tokens (budget 10K) - well within budget

## Scope

On the record entry page each medicine becomes its own block: the medicine name leads as a heading, and dose, frequency, and duration follow as term / definition pairs. A field with no value omits itself entirely, so a missing dose leaves no stray separator behind.

This is the change that makes a bare number legible. `9` under a `Dose` label reads as a data-entry problem a human can see and fix; `9 3 3` in a separator-joined string reads as nothing at all. Malformed existing data renders through the new layout **unchanged** - the fields become readable, not correct. No row is rewritten, no fixture or demo data is swept, and no migration exists.

The prescribing doctor is attributed beneath the medicine list, on the page that needs it, and the prescription reference stays visible so a record entry matches a physical prescription.

## Acceptance criteria

- [ ] Each medicine renders as its own block with the medicine name as a heading.
- [ ] Dose, frequency, and duration render as labelled fields.
- [ ] A field whose value is null, missing, or blank omits itself entirely, with no stray separator left behind.
- [ ] Malformed data still renders as labelled fields, so a bare number is visibly a data-entry problem rather than nonsense.
- [ ] The medicine-labelling helper is tested directly: all fields present, each field individually omitted, all fields omitted, and blank-string values treated as absent.
- [ ] The medicine-join helper becomes card-subtitle-only; the entry detail page no longer uses it for medicine rows.
- [ ] The prescribing doctor is attributed beneath the medicine list, and the prescription reference stays visible.
- [ ] No data migration and no content repair; existing rows render unchanged.
- [ ] Every existing data-testid on the record entry page is preserved.
- [ ] Every new label ships in English and Hindi.

## Read-list (in order)

1. The `#645` spec's "Prescription titles and medicine rendering" block, second paragraph onward, plus user stories 41–46. (~700 tokens)
2. The record entry detail page - **the medicine block, the attribution region, and the Rx reference line only**. Note the section headings you must preserve, and that its egress trail was already rewired by #654, so a shared import is already present on this page. (~1.2K)
3. The record entry detail page test suite - the prescription fixtures (including whatever malformed shape they already carry) and the assertions you must not break. (~1K)
4. The record timeline view-model's medicine helpers - the item extraction and the medicine-line joiner, whose role this ticket narrows to the card subtitle. You are adding a labelling helper beside it, not replacing it. (~400 tokens)
5. The dictionary file's record-detail namespace in **both** locales - the dose / frequency / duration labels and the attribution strings. (~500 tokens)

## Do NOT read

- `docs/archive/`.
- The record timeline **page**. You need the view-model module, not the page that renders cards - #655 changed that seam.
- The backend, the care API client, the doctor console, and the consent surfaces.
- The record entry page's other regions: its health summary, its documents, its consent citation, its timeline tab.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - expect **1 failed | 2024 passed**, the single pre-existing failure being `record/page.test.tsx > RecordPage access history > shows an empty state when there is no access history`. It fails on the untouched tree.
- `npm run typecheck` - **currently green.**

#655 must have landed: the card title and subtitle now carry the medicine name, so the entry page's block and the card must not duplicate the medicine name in a contradictory way. Verify before you start.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - the new labelling-helper cases green; every existing record entry assertion still green; the one pre-existing failure is still the only failure.
- `npm run typecheck` - `tsc --noEmit` is also the bilingual gate.
- `npm run lint`

## Handoff notes

- **The rendering changes, the data does not.** This is the easiest thing to get wrong: the temptation is to "fix" a bare `9` dose into `9 mg` while building the labelled layout. Do not. There is no migration, no repair, no fixture sweep. The labelled layout exists so bad data is _visible_; repairing it is a separate, deliberate data decision.
- **Blank-string is absent, not present-and-empty.** Existing data has both `null` and `""`. The helper must treat them identically, and a test must pin that, because `""` rendering as an empty definition list is the exact bug the "no stray separator" criterion is about.
- **The joiner survives, but with one caller.** #655 moved the medicine name and dose line into the card subtitle. After this ticket the joiner has exactly one consumer. Do not delete it here - the card subtitle still needs it, and deleting a shared helper is a cross-ticket change.
- **The attribution moves to the entry page on purpose.** The card shows the attributed doctor; the entry page repeats it beneath the medicine list. That is not duplication to avoid - the entry page is where a patient reads their prescription carefully, and the card is where they glance.
- **Keep the section headings.** `medicines`, `prescribedBy`, and `rx-reference` are the section labels the record page is navigated by. Preserve their test ids and their visual order.
- **The labels are the accessibility win too.** Term / definition pairs (`<dt>` / `<dd>`) mean a screen reader announces "Dose: 9" rather than reading three orphaned values in sequence. That is a second reason to use real definition lists instead of styled divs.
- **Hindi wrapping is not this ticket.** The Devanagari label-wrap problem is on the _doctor_ health background (#659), not here. If you notice the same collision risk in these labels, note it, do not fix it here.
