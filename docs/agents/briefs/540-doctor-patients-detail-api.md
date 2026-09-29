# Brief - 540 Doctor Patients detail API (consent-gated sections)

**Ticket:** #540 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Opening a patient from the doctor Patients list surfaces their full permitted context - contact details, photo, consultation history, a deep link into their case workspace, and, only when they granted the `health_background` scope, their health background (US-15, US-16, US-17, US-18). The detail read is section-gated on the patient's live grants: each section renders only under the relevant scope; the health-background section fails closed without a live `health_background` grant. Every doctor read of patient data in this route is access-logged and egress-disclosed against the authorizing grant (same discipline as the existing consented record read), and the photo read is the consented gated route, not an open URL.

AC:

- [ ] Detail read returns contact/photo/consultation history + a case-workspace deep link under the relevant grants; each consented section is access-logged + egress-disclosed
- [ ] Health background is returned only under a live `health_background` grant; a denial fails closed (gor denied-sections render as a locked "not shared" state on the client, not an error here)
- [ ] No live grant path returns nothing sensitive; methods are attached to an active doctor
- [ ] Facade + route tests (prior art: consented record read + egress tests); `npm run test:unit:backend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The consent gate + egress seam: `check_consent`, `record_egress_disclosure`, `_write_egress_log` in `modules/consent/facade.py` - the per-section gate and the disclosure call each consented section makes (~1.2K).
2. The consented-read discipline to copy: `read_consented_history` in `modules/health/facade.py` + `_log_access` (access-history row + `record.accessed`/`record.denied` outbox in the caller transaction) - the access/denial logging and fail-closed ordering including raise-after-commit on denial (~1.2K).
3. The identity profile enrichment + photo read surface: `get_patient_profile` (name/age/photo_ref) and the profile-media `read` port for the gated photo stream (never a public URL) (~0.6K).
4. The care case detail + deep-link shape: `fetchCareCase`-equivalent read in `case_facade.py` (case id + stage) that the client deep link targets (~0.5K).
5. The active-doctor guard (`_require_doctor` pattern) from the Patients-list ticket's seam (~0.2K).
6. Section-gating denial prior art: how the consented-read route returns denied sections without leaking (the denied shape the client renders as locked) (~0.5K).
7. Test prior art: consented read + egress route/facade tests (`test_health_record_route.py`, `test_consent_*` egress tests) (~1K).

## Do NOT read

- Frontend code, intake/care inner business logic beyond the case-link shape and stage, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - confirmed green 2026-09-24 (2338 passed).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - section-gating, fail-closed denial, access/egress logging, and guard tests green.
- `npm run lint`, `npm run typecheck` - clean.

## Handoff notes

- Blocked by #539 (same facade/route group) and #534 (the health-background content this section serves); run after both.
- The health-background denial must NOT 500: fail-closed means the section is absent/locked in the response, matching the client's locked "not shared" render.
- Every consented section is both access-logged and egress-disclosed against the specific authorizing grant (consent_id + version), the same two-ledger discipline as `read_consented_history`.
- The photo served here is the consented gated route; the profile-media `read` port backs it, never a public object URL.
- No em-dashes anywhere (lint-gated); use simple dashes.
