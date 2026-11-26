# Brief - 489 Review-queue enrichment

**Ticket:** #489 · **Parent:** #479 · **Refreshed:** 2026-09-19
**Reading surface:** ~4.5K tokens (budget 10K) - within budget

## Scope

Review-queue cards are triage-ready: patient name/age, an intake snippet, waiting time, section count. The review-queue read returns the extra fields (name/age from the identity profile, snippet + section count from the intake structured content) and the doctor console queue cards render them. No new access surface beyond the card fields.

AC:

- [ ] Review-queue read returns patient name/age, intake snippet, section count per item (waiting time already derives from created_at)
- [ ] Name/age resolve from the identity profile for the assigned intake; missing profile degrades gracefully
- [ ] Doctor console queue cards render name/age, snippet, section-count pills, waiting time, existing chips
- [ ] Read stays doctor-assigned-scoped; no PHI beyond the card's fields
- [ ] Route + page tests; bilingual parity

## Read-list (in order)

1. `modules/intake/facade.py` `list_review_queue` (L790) + `ReviewQueueItem` (`intake_models.py` L221-238) - the read to enrich (~700 tokens)
2. `modules/intake/adapters/routes.py` `GET /v1/intake/review-queue` (L272) - the route boundary (~300 tokens)
3. The identity profile read from ticket #482 (`save/get_patient_profile`) - the name/age source seam (~300 tokens)
4. `app/(doctor)/doctor/page.tsx` queue cards (L204-246) + `lib/intake/api.ts` `fetchReviewQueue` + `lib/care/api.ts` - fetch + render surface (~800 tokens)
5. `lib/i18n/dictionaries.ts` `doctorConsole` block + parity test (~500 tokens)
6. `tests/unit/test_doctor_review_queue_route.py` + doctor landing page test - test patterns (~600 tokens)

## Do NOT read

- Case workspace, rx lifecycle, pick flow, consent internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- Known pre-existing (unrelated): backend `test_app_shell` demo/OTP + `test_contract_check` fail under the local `DEFAULT_APP_ENVIRONMENT="dev"` override in `apps/backend/app/config.py`; frontend homepage parity fails on one Daltonganj string.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` + `npm run test:unit:frontend` - enriched payload route test + cards render test
- `npm run typecheck`

## Handoff notes

- Blocker #482 must be merged - name/age exist server-side only after `iam.patient_profiles` lands.
- Intake snippet/section count come from existing structured content, not a new AI call.
- Missing name should fall back readably (e.g. "Patient"), never a raw None crash.
