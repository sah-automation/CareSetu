# Brief - 12 Prescription-item editor refuses bare numbers

**Ticket:** #657 · **Parent:** #645 · **Refreshed:** 2026-10-06
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

The doctor's prescription-item editor refuses to issue an unreadable instruction. A dose, frequency, or duration that is a bare number with no unit is refused at save time with a message naming which field and why. Save is disabled while any row is invalid, and the refusal announces itself to assistive technology. This follows the save-refusal pattern the doctor profile's address card already established, rather than inventing a second one.

It is a **refusal, not a content rewrite**: nothing is corrected on the doctor's behalf and no row is silently dropped. The medicine name stays free text, so a real product name is never refused by an over-eager validator. An AI-drafted prescription stays editable into a valid state - a bad draft is fixable, not a dead end - and the hand-authored path is unaffected.

## Acceptance criteria

- [ ] A dose, frequency, or duration that is a bare number with no unit is refused.
- [ ] The refusal names which field and why, so the doctor can fix it rather than guess.
- [ ] Save is disabled while any row is invalid, so an invalid revision is never submitted.
- [ ] The validation error is announced to assistive technology, and the offending input is marked invalid and described by its error.
- [ ] The medicine name stays free text; a real product name is never refused.
- [ ] An AI-drafted prescription can be edited into a valid state and then saved; the draft itself is never blocked.
- [ ] A hand-authored, well-formed prescription still saves.
- [ ] Tests cover: bare-number dose refused, bare-number frequency refused, bare-number duration refused, free-text name accepted, save disabled while invalid, the error announced, and a well-formed row saving.
- [ ] Every existing prescription data-testid is preserved.
- [ ] Every new validation string ships in English and Hindi.

## Read-list (in order)

1. The `#645` spec's prescription-rendering block, third paragraph, plus user stories 47–52 - the bare-number refusal, the free-text name carve-out, the AI-draft-is-fixable rule, and the "prior art: the doctor profile address card" line. (~800 tokens)
2. The doctor profile **address section card only** - its validation pass, its validation hook, the refused-error hook, the announcement (`role="alert"` / live region), and the focus-walk to the first invalid input. This is the pattern you are replicating; copy its shape, not a new design. (~1.5K)
3. The address card's test suite - how it asserts a refusal, the announcement, and the disabled save. Your tests should read like these. (~1K)
4. The case workspace page - **the prescription editor region, the save handler, and the row state helpers only**. Note the existing prescription test ids you must preserve (`rx-row-{index}-*`, `rx-add-row`, `rx-remove-row-{index}`, `save-rx`, and whatever the AI-draft populate button uses), and how rows are added, removed, and seeded from an AI draft. (~2.5K)
5. The case workspace page test suite - the prescription-section describe, its fixtures, and the existing save-path assertions. (~1.5K)
6. The dictionary file's case-workspace namespace in **both** locales - the existing validation-message style to match. (~700 tokens)

## Do NOT read

- `docs/archive/`.
- The approval / rejection / close regions of the case workspace page. They are large, they are unchanged, and they carry their own test ids.
- The care API client beyond the two mutation signatures the editor calls.
- The backend. There is no server-side validation being added here; this is a client-side refusal plus a disabled save.
- The record surfaces - what a patient sees is #655 and #656's concern, not the doctor's authoring path.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - expect **1 failed | 2024 passed**, the single pre-existing failure being `record/page.test.tsx > RecordPage access history > shows an empty state when there is no access history`. It fails on the untouched tree.
- `npm run typecheck` - **currently green.**

No blockers. This ticket can start immediately.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - the seven editor cases green; every existing prescription-editor assertion still green; the one pre-existing failure is still the only failure.
- `npm run typecheck` - `tsc --noEmit` is also the bilingual gate.
- `npm run lint`

## Handoff notes

- **Refuse, never correct.** Do not append `mg`, do not parse "2x" into a dose, do not drop the row. The doctor's professional judgement is the input; a validator that rewrites it is a liability. The error message's job is to say _which_ field and _why_.
- **The bare-number rule is narrow on purpose.** It targets exactly `9`, `0.5`, `1` - a value that is _only_ digits, decimals, and whitespace. `9 mg`, `2 tablets`, `BD`, `9/3/3` all pass. A validator that rejects `2 tablets` will reject real prescriptions and will get switched off by whoever is annoyed enough to do so.
- **The name field is explicitly exempt.** Real product names contain numbers: "Zinc 20", "Vitamin D3 60k", "T-Bone 12". Validating the name against any numeric rule refuses legitimate medicines. This carve-out is an acceptance criterion, not a nicety.
- **A disabled save alone is not accessibility.** Announce the error, mark the input `aria-invalid`, and link it with `aria-describedby` - the address card already does all three. A silent disabled button tells a keyboard or screen-reader user nothing about why.
- **Focus walk.** On a refused save, move focus to the first invalid input. This is in the address card's pattern and it is the difference between "something is wrong" and "fix this specific field".
- **The AI draft must remain editable.** The refusal applies to the values, not to the draft's origin: a doctor who opens an AI draft, fixes the three fields, and saves must succeed. Test that path explicitly - it is the acceptance criterion most likely to regress.
- **Preserve every existing prescription test id.** The current suite is the editor's only regression net. Renaming `rx-row-{index}-dose` to something nicer silently deletes that coverage.
