# Brief - 539 Doctor Patients list API (Current/Past derivation)

**Ticket:** #539 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~5.5K tokens (budget 10K) - within budget

## Scope

A doctor gets a consent-gated list of the patients they are entitled to see, derived - never stored (US-11, US-12, US-13, US-14, US-19). The new doctor console facade returns two groups:

- **Current**: patients with a live standing grant to this doctor for any record scope, or an open (unclosed) care case assigned to them.
- **Past**: patients with only closed care cases and no live grant.

A patient stays listed until revocation of their last grant (Current) or remains in Past while a closed case exists. Each row carries the consent scopes granted to this doctor (with the new `health_background` scope once granted) and the latest care case stage. Name/age enrichment reuses the identity profile seam the review queue uses today. Light name search/filter as v1. Every list read is access-logged; this is a new facade + route group in the doctor console seam, gated to active doctors.

AC:

- [ ] `GET` list returns Current and Past groups derived from standing grants (counterparty = this doctor, granted) and assigned care cases, with no new patient-relationship table
- [ ] Rows show granted scopes and latest case stage; name/age/photo enrichment reuses the identity profile seam (degrade-safe like the review queue)
- [ ] Revocation moves a patient out of Current; only closed cases keep them in Past
- [ ] Name search/filter returns matches; non-doctor and non-active guards 403
- [ ] Facade + route tests (prior art: doctor case list + review-queue route tests); `npm run test:unit:backend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The consent grants-read surface for a patient (the facade seam behind `/v1/consents` GET) - listing live grants with counterparty, scope, and granted status; this is the Current-group source and the scope badge source (~0.6K).
2. The care case read surface: `list_doctor_cases` + the assigned-doctor resolver and `CaseStage` in `modules/care/case_facade.py` + `domain/state_machine.py` - the open/closed case derivation and latest-stage source (~1.2K).
3. The identity profile enrichment seam exactly as the review queue uses it: `list_review_queue` in `modules/intake/facade.py` (patient_name/age via `iam_facade.get_patient_profile`, degrade-safe try/except to anonymous cards) (~1K).
4. The active-doctor route guard: `_require_doctor` in `modules/care/adapters/routes.py` (require_partner -> resolve_partner -> partner_type != "doctor" or status != "Active" -> 403) - copy for the new route (~0.2K).
5. Doctor route/facade test prior art: `test_care_routes.py` case-list tests, `test_doctor_review_queue_route.py`, `test_doctor_review_queue_facade.py` (~1.5K).
6. #530's registered seam for the doctor console (whether `modules/doctor` or care/intake) - where the new facade + route group lands per the naming-authority ticket (~0.3K).

## Do NOT read

- Frontend code, patient health-background content tables (this is the summary list; content service is #540), `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - confirmed green 2026-09-24 (2338 passed).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - Current/Past derivation, revocation-moves-out, search, and guard tests green.
- `npm run lint`, `npm run typecheck` - clean.

## Handoff notes

- Requires #531 landed (`health_background` scope renderable) and #530's seam placement registered.
- Current and Past are derived on read; there is NO patient-relationship table - revocation is the only removal mechanic, exactly per the parent "reverse lookup over the standing-grant lineage" decision.
- Access-log every list read; the discipline to copy is `_log_access` style from the health consented read (row + outbox envelope), adapted to the doctor console seam.
- Past = patients with closed cases only AND no live grant; a patient with both an open case and a grant is Current.
- No em-dashes anywhere (lint-gated); use simple dashes.
