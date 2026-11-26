# Brief - 611 Retire the whole-form profile write and register four section routes

**Ticket:** #611 · **Parent:** #599 · **Refreshed:** 2026-09-30
**Reading surface:** ~10.4K tokens (budget 10K) - marginally OVER; drop read-list item 8 to land at ~9.3K

## Scope

With four section writes live, the single whole-form profile write - which required an address and coordinates on every save, so one bad field blocked every other edit - is removed. The doctor console page is its only consumer, and no consumer remains.

AC:

- [ ] The whole-form profile write route is no longer registered, and the route suite asserts its absence rather than merely not testing it.
- [ ] No request model still accepts latitude, longitude or the whole-form body shape.
- [ ] All four section writes remain reachable and keep their per-doctor idempotency scoping and active-doctor recheck.
- [ ] The consultation fee path, including its idempotency handling, and the photo upload and removal paths are unchanged.
- [ ] The full backend unit suite and the type check pass with no orphaned reference to the removed route or model.

This is a **deletion** ticket. Its read-list is the whole doctor-profile route surface, and that surface is what makes it marginally over budget.

## Read-list (in order)

1. The doctor-profile route module - the `router` declared with prefix `/v1/doctor`, and on it the five profile handlers: `get_doctor_profile`, `update_doctor_profile` (the whole-form write being deleted), `update_doctor_profile_photo`, `get_doctor_profile_photo`, `delete_doctor_profile_photo`, plus the module-level guards `_require_doctor` and `_resolve_subject_id` and the import block that pulls `DoctorProfileUpdate` out of the partner facade. Read from the module docstring down to the end of the photo handlers; the patients-list routes below them are not in scope. This is the edit site and the source of every guard the surviving routes inherit (~2.5K).
2. The doctor-profile IO models module - `DoctorProfileUpdate` (the body shape to delete, and the only place `practice_latitude`/`practice_longitude` are accepted from a client), `DoctorProfileView` (the surviving read projection), `DoctorProfilePhotoView`, `DoctorProfileCredential`, `DoctorCredentialStatus`. The whole module is small; read all of it (~0.8K).
3. `PartnerFacade` - two slices only, not the whole facade: the re-export block that surfaces `DoctorProfileUpdate as DoctorProfileUpdate` (the public-name re-export to retract, alongside the surviving `DoctorProfileView`/`DoctorProfilePhotoView` re-exports), and the `update_doctor_profile` method body (the write to delete, and the model of the `SELECT ... FOR UPDATE` + recheck + update-in-one-transaction shape the four section writes inherited from it) (~1.5K).
4. The doctor-profile route unit suite - `StubPartnerFacade` (its `update_calls` recorder and its `update_doctor_profile` method), the `_client` assembly helper (real `create_app`, stubbed facade, real tokens), the `test_put_doctor_profile_updates_editable_fields_for_active_doctor` test, and `test_profile_idempotency_key_is_scoped_to_the_doctor` (the two-identity replay proof). These are the tests the ticket replaces with an absence assertion; the photo tests in the same file stay as they are (~1.3K).
5. The doctor-profile facade unit suite - only the fake-engine scaffolding (`_connection`, `_Result`, `_Row`, the sequenced results) and the two tests that exercise `update_doctor_profile`, including the one that asserts it writes the private row only. Both tests go with the method; the scaffolding is reused by the surviving photo and read tests (~1.0K).
6. The gateway idempotency edge concern `run_idempotent(request, call, *, namespace=None)` and the `IdempotencyStore` it reads - specifically the cache-key construction and the store's in-process / TTL / bounded-dict discipline. Read this to settle the namespace question below, not to change it (~0.8K).
7. The route-inventory test `test_auth_routes_are_the_only_business_routes` in the app-shell suite, which pins an exhaustive set of `app.openapi()["paths"]` entries and today includes `/v1/doctor/profile`; plus the negative-OpenAPI precedent in the doctor patient-detail route suite, which asserts a retired path is absent from `app.openapi()["paths"]`. The first is the inventory the four section writes and this deletion must reconcile; the second is the pattern for "asserts its absence rather than merely not testing it" (~0.9K).
8. `docs/standards/api-standards.md` in full - route-inventory discipline. Read §1 (shape and versioning: base path versioned, additive changes do not bump) and §5 (idempotency and retries) as the load-bearing parts; §2, §3, §4, §6 and §6.1 are context for a deletion that removes no error shape (~1.1K). **This is the drop candidate** if you are over budget: §1 and §5 alone are ~0.3K and both are restated in read-list item 6.
9. `CONTEXT.md` - read only the build-session protocol and the "Doctor console & care loops (doctor-console/profiles batch)" glossary section. Do not read the whole file; the patient-identity, record-consent and event-bus sections are irrelevant to a route deletion (~0.5K).

## Do NOT read

- `docs/archive/` (never), anything under `docs/roadmap/`, and any `docs/architecture/` section beyond the partner module's inbound-interface line if you need to check a doc claim.
- The partner router module beyond the consultation-fee handler, and `PartnerFacade.update_consultation_fee`'s body. AC 4 is satisfied by confirming the two grep facts in Handoff notes, not by reading them. Verify with: the consultation-fee handler calls `run_idempotent(request, _call)` with **no** `namespace`, and it keys on the identity subject id rather than the partner id.
- The consultation-fee route unit suite.
- The doctor patients, case, review and media routes on the same doctor router; they are registered by the same module but are not part of the profile surface.
- Any other module's adapters, schema or facade; the care, intake, health, consent, iam, audit and partner-registration modules.
- Frontend. Nothing in `apps/frontend` blocks a type check on this deletion (see Handoff notes), and the frontend client for this route is a sibling ticket's business.
- Migrations and the alembic gate. This ticket writes no schema change.
- `PartnerFacade.get_doctor_profile`, `get_doctor_photo`, `delete_doctor_photo` bodies. The whole-form write's deletion does not touch the read projection or the photo paths.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - confirmed green 2026-09-30 on this tree (2628 passed); do not re-run to establish the baseline, re-run only to attribute a failure to your change.
- `npm run typecheck` - confirmed green 2026-09-30 (mypy `--strict` over 251 files, `tsc --noEmit` clean). This is the gate that proves no orphaned reference to the removed route or model survives (AC 5).

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - the doctor-profile route suite now asserts the whole-form write's absence rather than only omitting it; the four section writes' tests are green; the app-shell route inventory is reconciled; the photo and consultation-fee tests are untouched and green.
- `npm run typecheck` - no orphaned reference to the removed route handler, the removed facade method, or the removed request model in either `mypy --strict` or `tsc --noEmit`.
- `npm run lint` - pre-commit across all hooks (gitleaks, ruff, bandit, prettier, whitespace, the em-dash gate, the event-name gate, the module-boundary checker).
- `npm run test:integration` - optional but recommended: no integration suite exercises the whole-form write, so a green run here is a no-change signal, not evidence for AC 1. It **skips** unless a local native PostgreSQL is reachable.
- Not required: `npm run test:e2e` (needs the shared Playwright browsers), `npm run check:pages` (builds and serves the Next app; `/doctor/profile` is not in its channel set).

## Handoff notes

**Blockers, and what they will have landed by the time you start:**

- **#608** (practice section write) - replaces the whole-form write with a practice-section write: full name, clinic name, a multi-valued specialty selection validated against the closed list, years of experience. It carries the same `doctor:{doctor_id}` idempotency scoping, the same row-locked active-doctor recheck, and it extends the private read view with the new fields. It also lands the four section routes' first path in the doctor router.
- **#609** (address section write) - the structured address parts, and the practice position derived from the declared PIN rather than client-supplied coordinates. This is what finally makes latitude/longitude server-written only, so the "no request model still accepts latitude or longitude" half of AC 2 is closed by the union of #606 (removing them from the schemas) and this ticket (removing the last schema that had them).
- **#610** (about and notification section writes) - the about text, the notification preferences, and with #606 the closed-vocabulary languages and the consulting days/hours that replace the free-text `availability`.
- Transitive: **#602** (closed vocabularies for specialty, languages, consulting days) and **#606** (structured profile columns and multi-valued specialty storage, which drops the directory index specialty check constraint in favour of application-level validation and removes latitude/longitude from every update schema). #606 is the reason AC 2 has teeth: by the time you delete `DoctorProfileUpdate`, the section schemas already refuse coordinates.

**The idempotency namespace question (AC 3), answered from the live tree:**

- The cache key built inside `run_idempotent` is `"{namespace}:{request.url.path}:{key}"` when a namespace is supplied, and `"{request.url.path}:{key}"` when it is not. The request path is therefore always part of the key, whether or not a namespace is passed.
- Today exactly three handlers on the doctor router pass `namespace=f"doctor:{doctor_id}"`: the whole-form profile `PUT`, the profile photo `PUT`, and the profile photo `DELETE`. Only the first is being removed, and it holds the narrowest slice of the namespace (its own path). Nothing else in the repo shares the `doctor:` namespace - the other `run_idempotent` call sites are in the identity, care, intake, health, iam and partner routers, and every partner-router call site passes no namespace at all.
- **Nothing else was sharing this route's namespace, and nothing is left behind.** The store is in-process and per-process by design, its entries are TTL'd (the TTL derives from the OTP challenge lifetime constant, read through the iam facade) and its key count is bounded with prune-then-evict, so deleting a route leaves no durable key state to clean up and no migration to write.
- **The one thing to watch when the four section writes land:** if any section write is registered on the literal path `/v1/doctor/profile` (for example a `PATCH` on the same path rather than a distinct sub-path), then the key tuple stops separating the two writes and a client replaying an `Idempotency-Key` issued against the retired whole-form write would be served the section write's stored result. Give each section write its own path under the profile prefix. The existing per-doctor scoping on the surviving photo routes is already correct and must not be changed.
- The consultation-fee path is genuinely untouched and needs no edit: it is a `PATCH` on the **partner** router (not the doctor router), it passes no namespace, and it resolves the caller by identity subject id rather than partner id. AC 4 is satisfied by leaving it alone.

**Judgement calls made while mapping this surface:**

- The "route inventory" the ticket body alludes to is the exhaustive `app.openapi()["paths"]` set in the app-shell suite, which today lists `/v1/doctor/profile`. OpenAPI collapses methods, so that inventory tracks paths, not verbs: a bare removal of the `PUT` handler still leaves the path present because the profile `GET` shares it. AC 1's "no longer registered" therefore needs a **method-level** assertion (a `PUT` to the retired path answers 405/404, or the path item has no `put` operation), while the inventory edit handles the path-level bookkeeping the four section writes introduce. The doctor patient-detail route suite's negative-OpenAPI assertion is the in-repo precedent for the path-level half.
- **Ordering risk you own.** The doctor console profile page still calls the frontend doctor API client's `updateDoctorProfile` (the whole-form `PUT` to `/v1/doctor/profile`) at the point where it saves the page form. The page rebuild (#615 shell, #616 address card, #617 practice/about/notification sections) is a sibling in this batch and is not listed as a blocker of this ticket, so on a naive merge order this deletion lands while the page still calls the retired route, and the page's save breaks at runtime. `npm run typecheck` will **not** catch it: the frontend client types the request body itself, so removing the backend route leaves `tsc` green. Resolve it one of two ways - land this ticket after the page rebuild, or leave the frontend client function in place (it is dead code but harmless) and let the page-rebuild ticket remove it. Either way, do not delete the frontend `updateDoctorProfile` in this ticket: its two colocated suites mock it, and removing it is a frontend-ticket change.
- The contract check is not a gate here. The API/response contract checker parses the **auth** client only and never reads the doctor client, so a doctor route disappearing from the OpenAPI document does not fail it.
- Relevant ADRs: **ADR-0003** (db-per-module isolation) and **ADR-0020** (private profile-media bucket) both bound this surface - the retired write is a `partner_profiles` update inside the owning module, and the photo routes stay on the private `doctor/` media prefix, never a public URL. **ADR-0011** (credential expiry, lazy + daily sweep) is the reason the surviving private read view derives its credential statuses rather than storing them; do not touch that derivation while deleting the write.
