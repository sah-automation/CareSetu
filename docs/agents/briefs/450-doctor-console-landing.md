# Brief - 450 FE: doctor console landing (queue, cases, coming-soon, fee editor)

**Ticket:** #450 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~3.0K tokens (budget 10K) - within budget

## Scope

A new doctor dashboard replacing the placeholder: review-queue section (low-confidence first), open care-cases section, a consultation-fee editor so doctors can set their fee, Patients and Profile tabs reading coming-soon rather than broken links, and entries that link into the case workspace. Channel-gate test updated for the new heading.

AC:

- [ ] Console loads and shows the review queue (low-confidence first) and open care cases
- [ ] Patients and Profile render as coming-soon, not broken links
- [ ] Fee editor lets the doctor set their consultation fee (blank until set)
- [ ] Channel-gate test updated for the new doctor landing heading
- [ ] Console links into the case workspace for individual items
- [ ] All new copy is bilingual en/hi

## Read-list (in order)

1. Current doctor landing placeholder + the doctor layout + the channel-gate guard that routes authenticated doctors here - the replace/extend surface (~700 tokens)
2. Intake/care API clients for the review-queue read (#447 shape) and the existing doctor-scoped open-cases read - the two feeds this page merges (~600 tokens)
3. Partner client fee-update endpoint (#444 shape) - the editor's mutation (~300 tokens)
4. `lib/i18n/dictionaries.ts` `doctorConsole` block (skeleton from #446) + the page/component test pattern including the channel-gate test (~700 tokens)
5. Issue #438 user stories 11-16, 25-26 + "frontend - doctor console" decision (~600 tokens)

## Do NOT read

- Backend route internals, case workspace detail pages (#451-#453 build those), patient pick flow, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - currently green (71 files, 801 tests).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - page tests: queue shows low-confidence first, open cases render, coming-soon tabs, fee editor updates; channel-gate test passes with the new heading; parity test passes.

## Handoff notes

- Blockers #447 (queue read) and #444 (fee seam) must be merged.
- The workspace pages are separate tickets (#451-#453) - this ticket only builds the entry points and links into the workspace routes.
- All copy bilingual in the same pass.
