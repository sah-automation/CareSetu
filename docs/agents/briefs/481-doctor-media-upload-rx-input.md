# Brief - 481 Doctor media upload route (rx_input)

**Ticket:** #481 · **Parent:** #479 · **Refreshed:** 2026-09-19
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

Doctor-scoped media upload route storing voice/photo under the `rx_input/` storage prefix, returning a media reference usable as `DoctorInputRequest.media_ref`, mirroring patient intake upload (encrypted at rest, sensitive-class). The documented-but-unimplemented `rx_input/` prefix.

AC:

- [ ] Doctor-scoped upload accepts voice/photo bytes, stores under `rx_input/` (encrypted, durable), returns a media reference
- [ ] Only doctor-scoped callers succeed; partner/non-doctor and unauthenticated refused
- [ ] Returned ref usable as `DoctorInputRequest.media_ref` (existing doctor-input route)
- [ ] Upload failures answer the shared error envelope
- [ ] Route tests cover contract and ownership refusal

## Read-list (in order)

1. `modules/intake/adapters/media_store.py` - the store's PREFIX, `MediaFile`/upload seam, encrypt-at-rest, local/supabase backends; the `rx_input/` prefix must slot in here (~900 tokens)
2. Patient `POST /v1/intake/upload-media` route (`modules/intake/adapters/routes.py` L205-244) - the upload behaviour to mirror (multipart, `audio_duration_ms`, filename hygiene) (~500 tokens)
3. `modules/care/adapters/routes.py` `submit_doctor_input` (L266-296) + `DoctorInputRequest` (L101) - what media_ref the consumer accepts (~400 tokens)
4. `intake_models.py` `MediaFile` + `MediaUploadRef` (L65-117) - the typed upload contract (~400 tokens)
5. security-phii-standards uploads section + `docs/agents/briefs/385-intake-media-supabase-storage.md` (~600 tokens)
6. `tests/unit/test_care_routes.py` + a media route test - test patterns (~600 tokens)

## Do NOT read

- Prescription lifecycle internals, frontend, consent, AI pipeline, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- Known pre-existing (unrelated): `test_app_shell` demo/OTP + `test_contract_check` fail under the local `DEFAULT_APP_ENVIRONMENT="dev"` override in `apps/backend/app/config.py`; frontend homepage parity fails on one Daltonganj string.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - upload contract + ownership refusal tests
- `npm run typecheck`

## Handoff notes

- Ensure the seam respects module isolation (coding-standards S2): the media store is intake-owned; the /to-brief pass should resolve where the route surface lives (care vs intake adapter) without introducing cross-schema coupling.
- Storage durability/disposal mirrors patient intake media; `sensitive_class` flows to doctor-input (which records it on `care_doctor_inputs`).
