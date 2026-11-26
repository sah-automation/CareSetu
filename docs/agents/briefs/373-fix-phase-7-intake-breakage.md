# Brief - 373 Fix Phase 7 intake breakage: wire media store, allow text-mode voice note, migrate live DB, add doctor playback route

**Ticket:** #373 · **Parent:** #344 (Phase 7 spec, MOD-005) · **Refreshed:** 2026-09-10
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Ship the Phase 7 intake surface to its already-specified behavior (no new features, no schema changes):

1. **Wire the encrypted intake media store** into the intake facade so voice clips are AES-256-GCM encrypted under the `intake/` object prefix. `INTAKE_MEDIA_ROOT` (default `var/intake-media`) and `INTAKE_MEDIA_KEY` settings mirror the partner artifact store config.
2. **Allow text-mode intakes to carry an optional doctor-only voice note** (T17 brief): a `media_ref` rides with text, is persisted to `intake_media_refs`, is visible to the doctor, and is NEVER fed to `transcribe -> structure`. The strict one-mode rejection is removed.
3. **Apply the pending intake migration to the live DB** the running server uses (the repo `.env` `DATABASE_URL` value): `alembic upgrade head`, then verify the alembic version row at head and the `intake` schema tables exist.
4. **Add a doctor-scoped audio playback route** (`GET /v1/intake/{intake_id}/media/{media_ref_id}`) that decrypts and streams the clip to the owning patient or an allowed doctor partner.

Acceptance criteria (from ticket D1..D6):

- [ ] `POST /v1/intake/upload-media` succeeds and returns `MediaUploadRef` (store wired, 3-attempt resilience intact)
- [ ] `POST /v1/intake/submit` accepts `{ mode: "text", media_ref?: <MediaUploadRef> }` and persists the ref on the intake
- [ ] Text-mode audio is never transcribed; pipeline keeps `mode == "voice"` gate
- [ ] New `GET /v1/intake/{intake_id}/media/{media_ref_id}` streams decrypted audio to owning patient or doctor partner (doctor RBAC: partner scope + `partner_type == "doctor"`)
- [ ] Live DB at alembic head with `intake` schema tables
- [ ] Unit suite, lint, typecheck, scan all green

## Read-list (in order)

1. `apps/backend/modules/intake/facade.py` - `submit_intake` (lines 137-241; the text-mode rejection at 166-168 to relax, media-ref persistence block at 199-210 to generalize to text), `upload_intake_media` (lines 243-295; store-injection seam at 266, retry ladder to keep) (~2K tokens)
2. `apps/backend/modules/intake/adapters/media_store.py` - `IntakeMediaStore` (`save`/`_write` encrypt+filing only - NO read/decrypt path yet; D4 adds the mirror), `build_media_store` seam (line 93) (~1K tokens)
3. `apps/backend/app/config.py` - partner artifact settings: default const (line 56), dataclass fields (154-155), `get_settings` env mapping (439-442) - the pattern to mirror with `INTAKE_MEDIA_ROOT`/`INTAKE_MEDIA_KEY` (~0.5K tokens)
4. `apps/backend/app/main.py` - composition root: `build_artifact_store` wiring (189-192), `IntakeFacade(engine=engine)` at line 207 (THE breakage - no media store passed) (~0.5K tokens)
5. `apps/backend/modules/intake/adapters/routes.py` - submit route (131-155), upload-media route (158-191), doctor review route RBAC pattern to replicate (291-324), request models `SubmitIntakeRequest` (58-78), module error handlers (332-405) (~1.5K tokens)
6. `apps/backend/modules/intake/intake_models.py` - `MediaUploadRef` (55-69), `MediaRefView` (92-100), `MediaFile` (36-52) (~0.5K tokens)
7. `apps/backend/modules/intake/schema/models.py:184-210` - `intake_media_refs` table shape (no schema change, ref covers text-attached notes) (~0.5K tokens)
8. Tests (prior art + required updates) (~2K tokens):
   - `tests/unit/test_intake_media_rerecord.py` - facade-with-fakes seam: `_FakeMediaStore`, `_FakeSleep`, `_facade` helpers (lines 45-119) - the upload test harness to extend with a read/decrypt fake
   - `tests/unit/test_intake_facade_capture.py:300-317` - `test_submit_intake_text_mode_demands_text_rejects_media_ref` - THE old rejection to update to relaxed behavior
   - `tests/unit/test_patient_intake_routes.py` - `StubIntakeFacade` (122-147), submit/upload route assertions
   - `tests/unit/test_doctor_review_route.py` - doctor RBAC stub (66-78)
   - `tests/unit/test_app_shell.py:128-138` - route inventory set to extend with the playback route
9. `docs/standards/security-phii-standards.md` §5 (audio = PHI, private prefixes, encrypt at rest); `docs/architecture/internal-modules.md` §3.5 (MOD-005) (~0.7K tokens)

## Do NOT read

- `docs/archive/` (superseded by PRD), frontend sources
- Out-of-scope per ticket: device-local IndexedDB/OPFS audio storage, Phase 8 doctor channel (`/doctor/cases/<id>`), patient-side playback UI, S3-compatible cloud adapter, ASR/LLM tier changes
- Intake pipeline internals (`pipeline.py` body) beyond the mode gate - no change to `transcribe -> structure -> pre-summary` flow
- No schema/migration authoring - D3 is applying existing migrations, not writing new ones

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q` (from repo root)
- `node scripts/py.cjs -m ruff check apps/backend` and mypy per `npm run typecheck`
- **KNOWN RED: intake facade unit tests fail to COLLECT at HEAD** due to a pre-existing import cycle: `facade.py:26` (`from ...adapters.media_store import ...`) triggers `adapters/__init__.py:36` -> `pipeline.py:63` -> `from modules.intake.facade import INTAKE_SCHEMA`, but facade is partially initialized (INTAKE_SCHEMA set at line 115, after line 26). Affects `test_intake_facade_capture.py`, `test_intake_media_rerecord.py`, `test_intake_review_facade.py`. Route tests (`test_patient_intake_routes.py`, `test_doctor_review_route.py`) collect fine. Resolve this cycle (e.g. move `INTAKE_SCHEMA` definition above the facade imports, or import `INTAKE_SCHEMA` from a leaf module) as part of D1/D4 - the facade-seam tests are the primary test surface for this ticket.
- Local Postgres is at head `9f3c7cd8a409` (verified). The `.env` `DATABASE_URL` points at live Supabase - the D3 migration target; do not point local verification runs at it accidentally.

## Done-verify (acceptance criteria -> commands)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q` - all green, including the updated text-mode test and new playback/route tests
- `npm run lint`, `npm run typecheck`, `npm run scan` - clean
- `npm run migration-check` - alembic single-head + cross-schema FK scan
- Live-DB apply (D3): with `.env` loaded, `alembic -c apps/backend/alembic.ini current` shows `9f3c7cd8a409 (head)` and `intake.intake_intakes`, `intake.intake_media_refs`, `intake.pre_summaries` exist

## Handoff notes

- `IntakeFacade.__init__` already accepts `media_store` (facade.py:130, optional kwarg) - only the composition root fails to supply it. `upload_intake_media` already has the 3-attempt ladder and typed `MediaTransferError`; `IntakeMediaStore` encrypts at rest. The upload surface was built in T08 (#352) but never wired.
- `submit_intake` already inserts `intake_media_refs` for voice (facade.py:199-210) - text+note reuses that same insert path; only the validation at 166-168 rejects the combination today.
- `MediaTransferError` maps to 502, `IntakeValidationError` to 422, in `register_error_handlers` (routes.py:380-388, 350-358) - a new playback route's expected errors flow through these existing handlers.
- Doctor RBAC convention (from `mark_pre_summary_reviewed` route, routes.py:314-319): `require_partner` + `resolve_partner` + `partner_type == "doctor"` check raising `InsufficientScopeError` otherwise. Patient ownership is a facade-level check (`IntakeNotFoundError` when the intake isn't the caller's).
- D4 facade method signature suggestion: `get_intake_media(intake_id, media_ref_id, caller_id, caller_role)` returning decrypted bytes after ownership/doctor authorization; store gains a decrypt method mirroring `save` (read `<root>/<ref>`, nonce-prepended AESGCM decrypt).
- Route inventory assertion in `test_app_shell.py:63-138` must add the new playback path or it fails.
- Related briefs: #352 (T08 media store), #357 (T13 doctor review route), #344 (Phase 7 spec) - all prior art for the seams named here.
