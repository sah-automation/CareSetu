# Brief - 451 FE: case workspace - review, finalize, handshake

**Ticket:** #451 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~3.2K tokens (budget 10K) - within budget

## Scope

The case workspace review stage: opening a queued pre-summary or open care case lands in a workspace showing the case stage and any forced-review requirement; the doctor reads the full pre-summary and the patient's consented health history, finalizes a low-confidence pre-summary with a single attributed review action, and completes the consultation handshake into prescription-pending.

AC:

- [ ] Workspace shows the case stage and the forced-review requirement where applicable
- [ ] Doctor reads the full pre-summary and the consented history inside the workspace
- [ ] One review action attributes the review and finalizes a low-confidence pre-summary
- [ ] Completing the consultation handshake moves the case to prescription-pending
- [ ] All new copy is bilingual en/hi

## Read-list (in order)

1. The doctor console landing (#450) entry point and the workspace route it links to - the page shell this ticket fills (~500 tokens)
2. Intake client review read (#448 shape) + review action client (low-confidence finalize from #442) - read and mutate seams (~500 tokens)
3. Care client consented-history read (existing) + the consult-complete handshake mutation - groundwork for the step (~500 tokens)
4. `CONTEXT.md` care case / case stage / consult-complete milestone / forced doctor review glossary (~300 tokens)
5. Page-test pattern (vitest) + `lib/i18n/dictionaries.ts` doctorConsole block (~700 tokens)
6. Issue #438 user stories 13-16, 23-24 + "case workspace hosts the review" decision (~600 tokens)

## Do NOT read

- Prescription drafting/approval internals (that is #452/#453), backend route code, patient pick flow, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - currently green (71 files, 801 tests).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - workspace tests: stage + forced-review display, full pre-summary + consented history render, single-action finalize call, handshake moves to prescription-pending; parity test passes.

## Handoff notes

- Blockers #442 (finalize), #448 (pre-summary read), #450 (console) must be merged.
- The handshake is the consult-complete milestone on PreSummary → PrescriptionPending; do not build the rx UI here.
- All copy bilingual in the same pass.
