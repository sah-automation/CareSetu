# Brief - 494 PHASE-8.1 T10b: "N items edited by you" tracker in rx approval view

**Ticket:** #494 · **Parent:** #486 · **Refreshed:** 2026-09-19
**Reading surface:** ~2K tokens (budget 10K) - within budget

## Scope

In the approval view of the prescription workspace, the doctor sees a live "N items edited by you" summary before approving. The count is derived by comparing the working revision against the immutable AI-draft snapshot (name, dose, duration, frequency) and is display-only: the audit `edited_yn` semantics are unchanged, the UI merely shows what the audit already derives.

AC:

- [ ] The approval view shows "N items edited by you" when the working revision differs from the draft snapshot, counting items whose name/dose/duration/frequency differ
- [ ] A manual prescription (empty snapshot) reads as "all items edited"; an unedited AI draft reads as 0
- [ ] The count derives from data already returned by the working read + snapshot - no new audit writes
- [ ] Bilingual parity for the tracker copy in the `caseWorkspace` block
- [ ] Tests: frontend approval-view test (edited count across edited/clean/manual cases) + parity

## Read-list (in order)

1. The case-page review-decision section (page.tsx L1344-1399) - where the tracker renders above the approve gate; the `workingRx.draft_snapshot` + `workingRx.items` fields already present on the component state (~350 tokens)
2. `lib/care/api.ts` `PrescriptionDetailView` (L58-70, carries `draft_snapshot: Record<string, unknown>` and `items: RxItemView[]`) + the working-read fetch - the data both inputs come from (~200 tokens)
3. `modules/care/rx_facade.py` `_derive_edited_yn` (L89-109) - the audit comparison this mirrors client-side; keep the client derivation field-for-field identical (name/dose/duration/frequency), matching what #493 made symmetric (~250 tokens)
4. `prototype/phase-7-8/rx-approval.html` edit-tracker (L236 + JS L475-524) - the binding visual spec for the counter and per-row edit indicators (~250 tokens)
5. `lib/i18n/dictionaries.ts` `caseWorkspace` + Hi parity; the case-page `page.test.tsx` patterns (~400 tokens)

## Do NOT read

- Patient pick/intake consent internals, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 1056 passed, 3 failed (2 pre-existing jsdom navigation fails in `choose-role/page.test.tsx`, 1 Daltonganj parity string in `page.test.tsx`)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - new tracker tests pass (edited/clean/manual cases), parity green
- `npm run typecheck`

## Handoff notes

- Assumes #493 already landed: the comparison includes `frequency`, and the tracking guarantee (a frequency-only edit counts) comes from #493's `_derive_edited_yn` symmetry.
- Manual prescriptions carry an empty snapshot, so every item counts as edited - match the audit's behavior in `_derive_edited_yn`.
- Pure display slice: no schema, no API, no audit writes. If a count field looks tempting, don't add it - derive from data already on the component.
