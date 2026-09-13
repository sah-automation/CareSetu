# Brief - 389 Pre-summary degraded raw doctor review surface

**Ticket:** #389 · **Parent:** #388 · **Refreshed:** 2026-09-12
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

When a patient's intake is `ready_for_review` but has no AI pre-summary, the pre-summary page renders a meaningful "the doctor will review directly" surface instead of a "couldn't load" error banner: the raw symptom text for a text intake, or a "your recording has been shared with the doctor" confirmation for a voice intake, a patient-language explanation, a link back to the status page, and a live refresh so the patient is notified when the doctor acts. No "Continue to consultation" affordance is offered. In-progress and truly-failed intakes keep their current branches. Copy lands in both EN and HI with the same wording pattern as the rest of the intake flow. The degraded signature is detected client-side: pre-summary fetch returns the `INTAKE_NOT_FOUND` envelope AND intake detail reports `ready_for_review`. No backend or API contract change.

Acceptance criteria:

- [ ] A `ready_for_review` intake with no pre-summary row renders the degraded surface (not the error banner) on first load
- [ ] A `ready_for_review` intake reached mid-poll (from capturing/structuring) renders the degraded surface, not the "took too long" banner
- [ ] Text intakes show the raw symptom text as the evidence under review; voice intakes show a "recording shared with the doctor" confirmation
- [ ] The degraded surface links back to the status page and keeps a live refresh so the patient is notified when the doctor acts
- [ ] No confirm / continue-to-consultation affordance renders in the degraded state
- [ ] The degraded surface never shows a technical error (trace-id banner, "couldn't load")
- [ ] New copy present in both EN and HI dictionaries under the intake namespace; dictionary parity gate passes
- [ ] In-progress (captured/structuring) and failed/re-record branches behave exactly as before

## Read-list (in order)

1. Patient pre-summary page module `PreSummaryReviewPage` (`apps/frontend/src/app/(patient)/patient/intake/[intakeId]/pre-summary/page.tsx`) - the `load` function's `INTAKE_NOT_FOUND` branch (already re-reads intake detail; `ready_for_review` currently falls into the error banner), the poll effect's not-found path (`ready_for_review` currently falls through to "took too long"), the render branches (loading / processing / error / ready), and how the `intake.preSummary` copy strings are wired (~3.5K)
2. Intake data shapes `IntakeStatus`, `IntakeDetailView` (`mode`/`text`/`transcript`), `PreSummaryView` and the fetch helpers in `apps/frontend/src/lib/intake/api.ts` - the fields the degraded surface reads and the `INTAKE_NOT_FOUND` discriminator (~0.8K)
3. EN + HI `intake.preSummary` dictionary namespaces in `apps/frontend/src/lib/i18n/dictionaries.ts` - the shape new degraded keys must match (typed `Dictionary = typeof en`), plus the `dictionaries.test.ts` parity gate (missing keys fail) (~1.2K)
4. `page.test.tsx` for the pre-summary page - the `vi.mock("@/lib/intake/api")` pattern, the `intakeDetail()`/`preSummary()` builders, and the existing still-processing 404 suite where the new `ready_for_review` + 404 test belongs (~2.5K)
5. Poll constants `INTAKE_POLL_INTERVAL_MS` / `MAX_INTAKE_POLLS` in `apps/frontend/src/lib/intake/voice.ts` (~0.2K)

## Do NOT read

- The status page (`.../status/page.tsx`) internals - that seam is ticket #390
- Backend pipeline/adapters/routes · `docs/archive` · i18n infra beyond the intake namespace · other app surfaces

## Baseline verify (must pass before the first edit, verified 2026-09-12)

- `npm run test:unit:frontend` - 778 passed, 4 pre-existing failures unrelated to intake (`choose-role/page.test.tsx` x2, homepage EN/HI parity `app/page.test.tsx` x1, operator `verification/[partner_id]/page.test.tsx` x1)
- `npm run typecheck` - backend mypy clean (213 files); frontend tsc blocked by a stale generated `.next/dev/types/routes.d.ts` (truncated by an interrupted dev run, not source) - delete `apps/frontend/.next` and regenerate via `next dev`/`next build` once before typechecking

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - new `ready_for_review` + not-found degraded-branch tests plus the existing pre-summary page suite green
- `npm run typecheck` - clean after clearing the stale `.next` artifact

## Handoff notes

- The degraded signature is `error.code === "INTAKE_NOT_FOUND"` AND detail `status === "ready_for_review"`. Catch it in BOTH the initial-load and mid-poll paths; today `ready_for_review` lands in the error banner (load) and "took too long" (poll).
- No backend change and no new marker: the branch keys purely on existing status + not-found envelope.
- Degraded state replaces the error banner with: evidence (raw `text` for text mode; a recording-shared note for voice mode), a patient-language explanation, a back-to-status route link (currently absent - new), a live refresh, and NO confirm/continue CTA.
- New keys go under `intake.preSummary` in both locales in the same shape as neighbors; the parity test fails if one locale misses a key.
- Status-page ticket #390 adds its own degraded copy under the disjoint `intake.status` namespace of the SAME dictionaries file - land the two tickets sequentially on the branch.
