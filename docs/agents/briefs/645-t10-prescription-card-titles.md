# Brief - 10 Prescription cards titled by record type

**Ticket:** #655 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

A prescription card on My Record is titled "Prescription", so a patient can tell what kind of record they are looking at without inferring it from a drug name. The medicine name moves into the subtitle, which carries the dose line, the prescribing doctor, and the date - so the card answers "what, how much, by whom, when" at a glance. The medicine name is not lost, it moves.

This is done at the one shared describe / format seam that shapes both the My Record timeline and the dashboard's recent-activity preview, so the two surfaces cannot disagree about what a prescription is. A prescription that attributes a doctor shows that doctor; one that does not gets a neutral phrase rather than an invented name. A multi-medicine prescription still reports the remainder count rather than silently truncating, and a prescription with no items keeps its lean form.

## Acceptance criteria

- [ ] A prescription card's title is the record type, not the first medicine's name.
- [ ] The subtitle carries the dose line, the prescribing doctor, and the date.
- [ ] A payload that attributes a doctor shows that doctor's name; one that does not get a neutral phrase, never an invented doctor.
- [ ] A multi-medicine prescription still reports the remainder count.
- [ ] A prescription with no items keeps its current lean form.
- [ ] The dashboard's recent-activity preview carries the same presentation, because it comes from the same seam.
- [ ] The view-model is tested directly: single-medicine title and subtitle, multi-medicine remainder, no-item lean form, and both languages.
- [ ] Every new string ships in English and Hindi.

## Read-list (in order)

1. The `#645` spec's "Prescription titles and medicine rendering" block, first paragraph, plus user stories 35–40. (~700 tokens)
2. The record timeline view-model module - the describe / format entry point in full, and inside it: the prescription branch, the medicine-item extraction, the attribution and chemist-name helpers, and the medicine-line joiner. Also the badge-tone and type-badge maps, because the card's badge is part of the same return value. (~2.5K)
3. The view-model's test suite in full - the fixtures, the assertion style, and the existing prescription cases you are changing rather than duplicating. (~2K)
4. The dictionary file's record namespace in **both** locales - the badge map (which already holds the prescription type label you need as the new title), the issued-by / neutral / prescribed-by strings, and the remainder-count function. (~800 tokens)

## Do NOT read

- `docs/archive/`.
- The record entry detail page's **medicine block** - that rendering is #656's. You are changing the card view-model, not the per-entry medicine list.
- The record timeline page beyond the single call site that consumes the view-model.
- The care API client and the backend - the payload shape is unchanged.
- Every other describe / format consumer beyond noting that they all call the same function (the timeline, the entry page, the recent-activity card, and the health snapshot card). They cannot drift, because there is one seam.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - expect **1 failed | 2024 passed**, the single pre-existing failure being `record/page.test.tsx > RecordPage access history > shows an empty state when there is no access history`. It fails on the untouched tree.
- `npm run typecheck` - **currently green.**

No blockers. This ticket can start immediately.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - the view-model cases green in both languages; the record page and dashboard preview suites still green because they read the same seam.
- `npm run typecheck` - `tsc --noEmit` is the bilingual gate.
- `npm run lint`

## Handoff notes

- **One seam, four consumers.** The timeline page, the record entry page, the dashboard's recent-activity card, and the health snapshot card all call the same describe / format function. Changing it once corrects all four and makes drift between them structurally impossible. Do not add a second formatting path "just for" a surface - that is the failure this ticket exists to prevent.
- **The title moves, it does not disappear.** The medicine name is what the subtitle is for. A card titled "Prescription" whose subtitle omits the drug is a worse card than today. Keep it prominent.
- **The doctor name comes from the payload, never invented.** The payload already carries an attributed doctor and the helper already extracts it; a payload that attributes none must fall to the existing neutral phrase. Do not add a "prescribed by CareSetu" style default - that reads as a real clinician.
- **The medicine-line joiner stays for the subtitle only.** #656 moves the entry detail page off it. Until that lands the joiner has two callers; you are not removing it in this ticket.
- **The no-items lean form is a separate branch** with its own title path and its own Rx reference line. It already works; keep it working.
- **A record-type title is a dictionary string, not a literal.** The prescription badge label already exists in the record namespace and is the right string for the title. Reuse it rather than adding a near-duplicate - that is how the two surfaces drift.
