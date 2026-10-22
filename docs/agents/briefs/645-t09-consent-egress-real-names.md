# Brief - 09 Consent log, egress table and record-entry egress trail render resolved names

**Ticket:** #654 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Every patient-facing surface that shows who has access to a health record shows a name instead of a number. Three render sites consume the fallback chain from the preceding ticket:

- the consent log card, which now also states the counterparty's role in words so "Dr A Kumar" also tells the patient they are a doctor;
- the consent log's egress table "To whom" column, so a patient can audit who has actually received their data;
- the record entry page's egress trail, so "who has seen this entry" is answerable without reading database keys.

The AI intake row is visibly the AI in both tables. The control that actually protects the patient is untouched: the consent card keeps its state badge, its consent version, its timestamps, its receipt, and its revoke action.

## Acceptance criteria

- [ ] The consent log card shows the counterparty's resolved name, and the role in words alongside it.
- [ ] The consent card's state badge, consent version, timestamps, receipt, and revoke action are all preserved unchanged, and remain auditable now that a name arrives.
- [ ] The egress table's "To whom" column shows a name.
- [ ] The record entry page's egress trail shows counterparty names.
- [ ] The AI intake counterparty reads as the AI on both the egress table row and the egress-trail row.
- [ ] A consent card whose counterparty cannot be resolved says "Doctor" or "Pharmacy" rather than a bare number.
- [ ] No opaque identifier is ever the only thing shown on any of the three surfaces.
- [ ] Page tests assert a resolved name, a type-derived fallback, and the AI label on each surface, and the existing state / receipt / revoke assertions still pass.
- [ ] Every new consent, record, and prescription string on these surfaces ships in English and Hindi.

## Read-list (in order)

1. The `#645` spec's consent-log and egress user stories (24–34) and the "Real names in the consent log" solution paragraph - the three-step chain, the role-in-words requirement, and the "a security reviewer wants no opaque identifier on any patient-facing surface" story. (~700 tokens)
2. The counterparty label and initials helper module, from #653's diff. (~200 tokens)
3. The consent-log page - **the three regions only**: the module constants and dictionary wiring at the top, the egress-table section, and the `ConsentCard` component with its revoke handling. (~1.5K)
4. The consent-log page test suite - the fixture builders, the consent-card assertions, and the egress-slice describe. (~1.5K)
5. The record entry detail page - **the egress-trail section only**, plus how it filters the log and reuses its first row for the consent citation. (~600 tokens)
6. The record entry detail page test suite - the egress-trail describe and the fixture shape. (~600 tokens)
7. The dictionary file's consent-log and record-detail namespaces in **both** locales. (~600 tokens)

## Do NOT read

- `docs/archive/`.
- The rest of either page. The consent-log page is 500 lines and the record entry page 440; the egress and consent-card regions are what this ticket changes. The record entry page's **medicine block** is #656's.
- The backend consent facade and routes - the wire field is already delivered and pinned.
- The patient profile consent panel and the action-required card. They consume the same helper and benefit for free; they are not in scope.
- The record timeline page.
- Any doctor console surface.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - expect **1 failed | 2024 passed**, the single pre-existing failure being `record/page.test.tsx > RecordPage access history > shows an empty state when there is no access history`. It fails on the untouched tree.
- `npm run typecheck` - **currently green.**

#653 must have landed. Verify the helper's three-step chain exists before you start.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - new assertions on all three surfaces green; every existing consent-card state, receipt, revoke, stop-forward, and egress-header assertion still green; the one pre-existing failure is still the only failure.
- `npm run typecheck` - `tsc --noEmit` is also the bilingual gate.
- `npm run lint`

## Handoff notes

- **The record entry page does not import the label helper at all today.** It inlines the counterparty type and id directly in the egress-trail row, which is the asymmetry that let the two surfaces drift. This ticket replaces that inline rendering with the shared helper - do not leave a second inline path behind.
- **The consent card's existing testids are per-id families** (`consent-{id}`, `receipt-{id}`, `revoke-{id}`, `stop-forward-{id}`). Preserve them exactly; the patient-journey e2e spec selects on those prefixes, and renaming one silently narrows the e2e coverage instead of failing it.
- **Do not disturb the control that protects the patient.** The state badge, the revoke sheet's confirm / cancel / toast, and the revoked stop-forward notice are the parts of this page a patient actually acts on. Adding a name next to them must not reorder them, restyle them, or move focus.
- **The egress table's headers are asserted by the existing e2e spec**, including "To whom". Only the cell content changes; the header text does not.
- **The consent version and the lineage reference stay on the card.** The name is an addition. The receipt cites lineage plus version for audit, and a patient who now sees a name still needs the machine-checkable reference behind it.
- **"Role in words" is a separate string from the name.** "Dr A Kumar" plus "Doctor" reads better than a concatenated "Dr A Kumar (Doctor)", and in Hindi a paren reads worse. Two fields, both bilingual.
- **The AI row must be unmistakably the AI on both tables**, not merely not-a-doctor. A patient needs to know a machine read their intake.
