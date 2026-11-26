# Brief - 14 Profile header band and scannable health-background chips

**Ticket:** #659 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The doctor patient profile stops reading as a form. The header leads with a large avatar and the patient's name, so a doctor knows at a glance whose profile they opened, and age and gender render as inline chips rather than a stacked list.

The health background's conditions, allergies, medications, immunizations, and family history render as chips a doctor can scan individually, instead of one comma-joined run-on, and their labels wrap gracefully in Hindi so a long Devanagari label never collides with its value.

Nothing about access changes. A locked section still renders as the calm "not shared" state - never an error, never a leak - and the photo keeps coming from the consent-gated photo route, never from a reference on the wire.

## Acceptance criteria

- [ ] The profile header leads with a large avatar and the patient's name.
- [ ] Age and gender render as inline chips, so the header reads as one band rather than a stacked form.
- [ ] The health background's conditions, allergies, medications, immunizations, and family history render as chips rather than a comma-joined run-on.
- [ ] The health background labels wrap gracefully in Hindi; a long label never collides with its value.
- [ ] A locked section still renders as the calm "not shared" state, never an error and never a leak.
- [ ] The photo still comes from the consent-gated photo route; no photo reference is ever read from the wire.
- [ ] Page tests assert the header band, the health-background chips, and the preserved locked-section behaviour.
- [ ] Every new label and chip ships in English and Hindi.

## Read-list (in order)

1. The `#645` spec's profile user stories (61–65) plus the doctor-profile solution paragraph - the header, the chips, the Hindi wrapping, and the two "unchanged" clauses (locked section, photo route). (~600 tokens)
2. The doctor patient profile page - **the contact / header block, the health-background block, the locked-section component, and the photo resolution effect**. That last one is the consent gate: confirm the photo is fetched from the gated route and that no reference field on the wire is being read. (~1.8K)
3. The doctor patient profile page test suite - the fixtures, the locked-section assertions you must not break, and the existing photo tests. (~1.2K)
4. The avatar primitive's usage contract - its precedence chain, its sizing rules, and its "consumers size it via className and never fork the chain" note. You are asking for a **large** avatar, which is exactly the case that note warns about. (~400 tokens)
5. The dictionary file's doctor-patients namespace in **both** locales - the existing labels, and where chip rendering gets its strings. (~600 tokens)
6. `docs/design/ui-blueprint.md` - the doctor surface's list and detail sections for the header band and chip conventions. (~900 tokens)

## Do NOT read

- `docs/archive/`.
- The backend detail read. Its shape is unchanged, and the photo reference question is answered by the frontend effect, not the payload.
- The doctor patients list page - #651 already made the card decisions, and the header here is a different surface.
- The case workspace page and every patient-facing surface.
- The care API client beyond the profile read's existing type.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - expect **1 failed | 2024 passed**, the single pre-existing failure being `record/page.test.tsx > RecordPage access history > shows an empty state when there is no access history`. It fails on the untouched tree.
- `npm run typecheck` - **currently green.**
- `npm run check:pages` - the page-weight budget; the header gains an avatar instance, so measure rather than assume.

No blockers. This ticket can start immediately.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - new header and chip assertions green; the existing locked-section and photo assertions still green; the one pre-existing failure is still the only failure.
- `npm run typecheck` - `tsc --noEmit` is also the bilingual gate.
- `npm run lint`
- `npm run check:pages`

## Handoff notes

- **The photo is a gate result, not a wire field.** The profile already fetches the photo through the consent-gated route and the reference never reaches the client. That is the correct architecture and it is an acceptance criterion that you **preserve**. While you are in the header block, confirm you are rendering the effect's result - and do not "simplify" by reading a `photo_ref` off the profile payload, which is exactly what #651's cards also declined to do.
- **Large avatar, no forked chain.** The avatar primitive sizes by `className` and its precedence chain is a contract. A large header avatar is a `className`, not a new component and not a reordered chain.
- **Chips must wrap, not overflow.** A comma-joined string has no wrap problem; a row of chips does. Use a wrapping flex container so a long allergy list becomes more rows instead of a horizontal scrollbar. This is the same rule the case grid obeys.
- **Hindi is where the layout breaks.** Devanagari labels are longer and unbreakable in ways English labels are not - "उपचार इतिहास" next to its value is where a naive `whitespace-nowrap` fails. Let the **label** wrap and keep the value readable. This is the acceptance criterion the English-only reviewer forgets to check.
- **Chip semantics.** A chip is a Badge; it is not interactive here. Do not make it a button, and do not add a remove affordance - these are read-only facts about a patient.
- **The locked section is the most important thing not to break.** A "not shared" state must stay calm. If the health background becomes chips, a locked health background must become locked chips or keep its existing calm rendering - not an error card, and not an empty chip row that implies "no conditions" when the truth is "not shared". That distinction is the whole point of the section.
- **"No conditions" and "not shared" must remain visually different.** Rendering a locked section as an empty chip list would tell a doctor a patient has no allergies when the answer is unknown. Preserve the wording and keep the locked treatment.
