# Brief - 533 Patient profile photo upload/remove

**Ticket:** #533 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

A patient can upload, replace, preview and remove their own profile photo through the `/v1/me/*` surface - the photo uploads into the private `profile-media` store (patient prefix) and only a storage key is persisted on the patient profile (US-20). Reads stream through the backend (own-photo read for the session user only); a doctor's read of a patient photo happens later through the consent-gated doctor detail route, never this endpoint. Photo refs are keys, so an image-resize step can slot in later without an API change.

Validation: content-type JPEG/PNG/WebP only, size <= 5MB, GIF rejected. The photo is bound to the current session patient, replaces any existing photo, and removal clears the stored key.

AC:

- [ ] `PUT`/`DELETE` own-photo endpoints store/clear the photo key in `profile-media` (patient prefix) and persist it on the patient profile; the existing profile model's photo-ref field is used
- [ ] Content-type and size validation is enforced (JPEG/PNG/WebP, <= 5MB, GIF rejected) with the standard error envelope
- [ ] Reads stream through the backend for the session owner only; no public URL is ever served
- [ ] Route/facade tests cover upload, replace, remove, and the validation rejects (prior art: existing profile routes tests and intake doctor-media upload); `npm run test:unit:backend`, `npm run lint`, `npm run typecheck`, `npm run migration-check` green

## Read-list (in order)

1. The `/v1/me` route group in `app/main.py` (GET `/v1/me`, GET/PUT `/v1/me/profile`) - where the photo surface joins the existing route group and the profile response typed-not-set pattern (~0.6K).
2. The identity profile seam: `save_patient_profile` and `get_patient_profile` in `modules/iam/identity_facade.py`, the `PatientProfile` Pydantic model (the dormant `photo_ref` field, `extra="forbid"`), and the `iam_patient_profiles` table `photo_ref` column (~1K).
3. The profile-media port from #532 - `build_*_media_store` factory and the `save`/`read` port shape the patient prefix uses (grep the shipped adapter) (~0.3K).
4. Intake doctor-media upload prior art - the upload route + facade + validation shape to copy for content-type/size enforcement (grep doctor-media upload in intake routes/facade) (~0.6K).
5. `tests/unit/test_profile_routes.py` - the GET/PUT profile test patterns to extend (~1K, only the relevant test functions).
6. `docs/standards/security-phii-standards.md` uploads section - content-type/size rules and stream-through-backend requirement (~0.5K).

## Do NOT read

- Frontend code, care/health module internals, `docs/archive/`, the supabase/local backend internals of the profile-media store (only its port).

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - confirmed green 2026-09-24 (2338 passed).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.
- `npm run migration-check` - confirmed green 2026-09-24 (single head `ca8d2419f2b6`).

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - new photo upload/replace/remove + validation-reject tests green.
- `npm run lint`, `npm run typecheck`, `npm run migration-check` - clean.

## Handoff notes

- `photo_ref` already exists end-to-end on the patient profile (model + table + migration) - this ticket activates it, it does not create a column.
- The doctor's read of a patient photo is explicitly later work (#540), never this endpoint: this surface answers only the session owner's own photo.
- Store only the object key on the profile; blob streaming for the owner read goes through the profile-media `read` port, never a public URL.
- No em-dashes anywhere (lint-gated); use simple dashes.
