# Brief - 453 FE: case workspace - approve, reject, close

**Ticket:** #453 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~2.6K tokens (budget 10K) - within budget

## Scope

Issuance and closure in the case workspace: approve the reviewed prescription with the mandated verification declaration, see the issued prescription after approval, reject a draft with a reason, or close the case without prescribing. Each action reflects the delivered backend behavior and renders bilingual.

AC:

- [ ] Approval is accepted only with the verification declaration, and shows the issued prescription after approval
- [ ] Rejecting a draft records a reason the patient can understand
- [ ] Close-without-prescription moves the case to Closed and off the pending list
- [ ] All actions use the care API client with the idempotency-key header
- [ ] All new copy is bilingual en/hi

## Read-list (in order)

1. The case workspace page from #452 (drafting stage) - the surface that gains approve/reject/close actions (~400 tokens)
2. Care API client approve / reject / close-without-prescription endpoint signatures (existing backend) + the idempotency-key helper from #446 (~500 tokens)
3. The issued-prescription view after a successful approval - what the patient receives, rendered here for the doctor (~300 tokens)
4. `CONTEXT.md` verification declaration / revised-yn / close-without-prescription glossary (~300 tokens)
5. Page + client vitest patterns + `lib/i18n/dictionaries.ts` doctorConsole block (~700 tokens)
6. Issue #438 user stories 19-22 (~400 tokens)

## Do NOT read

- Backend route code, AI-draft/revision internals (that is #452), patient pick flow, `docs/archive/`, review-stage internals.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - currently green (71 files, 801 tests).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - workspace tests: approve gated on the declaration, issued rx rendered after approval, reject persists a reason, close moves stage to Closed; idempotency header asserted; parity test passes.

## Handoff notes

- Blocker #452 must be merged.
- No approval issues without the declaration: the UI must not send the approve request unless the declaration is true (mirrors revision-freeze approval).
- All copy bilingual in the same pass.
