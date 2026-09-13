# Brief - 390 Status page gates Continue affordance + raw review note

**Ticket:** #390 · **Parent:** #388 · **Refreshed:** 2026-09-12
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

The patient intake status page stops pointing a Ready-for-Review patient at a pre-summary that does not exist. When the intake is `ready_for_review` but has no pre-summary, the page no longer renders the "Continue to consultation" affordance that dead-ends on the missing page, shows a patient-language raw-review note instead (EN + HI), and no longer flips the whole page to an error banner on first load just because the conditional pre-summary fetch returns not-found. Processing and truly-failed intakes keep their current branches. Detection is client-side: `ready_for_review` status + pre-summary not-found (`INTAKE_NOT_FOUND`). No backend or API contract change.

Acceptance criteria:

- [ ] Ready-for-Review intake with no pre-summary: no "Continue to consultation" affordance renders
- [ ] Ready-for-Review intake with no pre-summary: the raw-review note renders instead (EN + HI)
- [ ] Ready-for-Review intake with no pre-summary: first load does not flip the page to an error banner
- [ ] Ready-for-Review intake WITH a pre-summary keeps the current continuation affordance and copy
- [ ] Capturing/structuring and failed/re-record branches unchanged
- [ ] New status-namespace copy present in both EN and HI dictionaries; dictionary parity gate passes

## Read-list (in order)

1. Patient intake status page module `IntakeStatusPage` (`apps/frontend/src/app/(patient)/patient/intake/[intakeId]/status/page.tsx`) - `load` (conditional `fetchPreSummary` only when ready, whose not-found currently flips the whole page via the shared catch), refresh (silently swallows pre-summary failure), the poll loop, the `isReady` gate, the continue-zone JSX (gated on status only; the `preSummary` state is never read in JSX today), and the `STATUS_STEPS` mapping (~2.5K)
2. EN + HI `intake.status` dictionary namespaces in `apps/frontend/src/lib/i18n/dictionaries.ts`, including `readyForReviewDesc` (currently promises the pre-summary is ready) - where the raw-review note and the no-pre-summary ready copy land (~1K)
3. `page.test.tsx` for the status page - the `vi.mock("@/lib/intake/api")` pattern, `intake()`/`preSummary()` builders, and the existing "hides the continue affordance until the pre-summary is ready" test (currently exercised with `structuring`) where the ready + no-pre-summary case belongs (~2K)
4. Intake data shapes + fetch helpers in `apps/frontend/src/lib/intake/api.ts` - status values and the `INTAKE_NOT_FOUND` discriminator (~0.5K)

## Do NOT read

- The pre-summary page (`.../pre-summary/page.tsx`) internals - that seam is ticket #389
- Backend · `docs/archive` · i18n infra beyond the intake namespace · other app surfaces

## Baseline verify (must pass before the first edit, verified 2026-09-12)

- `npm run test:unit:frontend` - 778 passed, 4 pre-existing failures unrelated to intake (`choose-role/page.test.tsx` x2, homepage EN/HI parity `app/page.test.tsx` x1, operator `verification/[partner_id]/page.test.tsx` x1)
- `npm run typecheck` - backend mypy clean (213 files); frontend tsc blocked by a stale generated `.next/dev/types/routes.d.ts` (truncated by an interrupted dev run, not source) - delete `apps/frontend/.next` and regenerate via `next dev`/`next build` once before typechecking

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - new ready + no-pre-summary tests plus the existing status page suite green
- `npm run typecheck` - clean after clearing the stale `.next` artifact

## Handoff notes

- Two distinct fixes on one page: (1) absorb the not-found on first load as the degraded state instead of letting the shared catch flip the page to the error banner; (2) gate the Continue affordance on pre-summary PRESENCE, not just `isReady`.
- The raw-review note replaces or reframes the `readyForReviewDesc` wording for the no-pre-summary case - user story 5 (#388) demands the Ready-for-Review state describe how the doctor will use the intake accurately.
- After a manual refresh with ready + no pre-summary the page already keeps `preSummary === null` (swallow) - the degraded note must render there too, matching the initial-load branch.
- New keys go under `intake.status` in both locales in the same shape as neighbors; parity test fails if one locale misses a key.
- Pre-summary-page ticket #389 adds its copy under the disjoint `intake.preSummary` namespace of the SAME dictionaries file - land the two tickets sequentially on the branch.
