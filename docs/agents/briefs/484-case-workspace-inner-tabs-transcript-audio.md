# Brief - 484 Case workspace inner tabs + transcript + audio

**Ticket:** #484 · **Parent:** #479 · **Refreshed:** 2026-09-19
**Reading surface:** ~5.5K tokens (budget 10K) - within budget

## Scope

The case workspace stops being one stacked column: it gains Pre-summary / History / Prescription inner tabs. The Pre-summary tab shows the original intake transcript text and a playback control for the intake audio (via the existing `GET /v1/intake/{intake_id}/media/{media_ref_id}` stream route). Small additive backend delta: a doctor-ownership-scoped intake-detail read returning transcript + media refs for a case's intake (today the detail read is patient-only; the doctor pre-summary read carries neither). Access stays assignment-scoped, PHI-safe, no new cross-schema coupling.

AC:

- [x] Workspace organized into Pre-summary / History / Prescription inner tabs; not one stacked column
- [x] Pre-summary tab shows the original intake transcript text and an audio playback control (existing media-stream route)
- [x] Doctor-scoped intake-detail read (transcript + media refs) added, ownership-scoped, additive, no cross-schema coupling
- [x] Stage locks/jumps between tabs behave like the prototype (pre-summary stage lock names what is missing)
- [x] Tests: backend route test for the doctor intake-detail read; transcript/playback rendering test; bilingual parity

## Read-list (in order)

1. `app/(doctor)/doctor/cases/[caseId]/page.tsx` - the single stacked column (sections from L437, prescription drafting L540-936) that becomes tabs (~1.6K tokens, relevant slices)
2. `modules/intake/facade.py` `get_intake` (L442-500, patient-only, assembles `MediaRefView` list) + `get_doctor_pre_summary` (L856-930, doctor-scoped predicate) - the two reads the new doctor intake-detail read blends (~1.2K tokens)
3. `modules/intake/intake_models.py` `IntakeDetailView` (L163-183, has `transcript` + `media_refs`), `MediaRefView` (L139-147) - the payload shape (~300 tokens)
4. `modules/intake/adapters/routes.py` `GET /v1/intake/{intake_id}/media/{media_ref_id}` (L474-521, dual-role doctor branch already exists) + `GET /v1/intake/{intake_id}` (L333-352, patient-only today) - where the new doctor read slots next to the existing stream route (~500 tokens)
5. `app/(doctor)/doctor/review/[intakeId]/page.tsx` - pre-summary render patterns (structured fields, confidence chip, finalize) (~600 tokens)
6. `lib/intake/api.ts` - `PreSummaryView` / `fetchIntake` view models; the doctor page currently has no transcript/media handle (~400 tokens)
7. `prototype/phase-7-8/case-workspace.html` - binding visual spec: `.tabs` data-tabs (L219-222), `.transcript-box` (L239-240), `.audio-link` (L243-245), stage locks (~400 tokens)
8. `lib/i18n/dictionaries.ts` `caseWorkspace` block + `dictionaries.test.ts` parity walk; case-workspace page test `vi.mock` pattern (~600 tokens)

## Do NOT read

- rx lifecycle internals, consent module, patient intake capture/voice pages, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- Known pre-existing (unrelated): backend `test_app_shell` demo/OTP + `test_contract_check` fail under the local `DEFAULT_APP_ENVIRONMENT="dev"` override in `apps/backend/app/config.py`; frontend homepage parity fails on one Daltonganj string.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - doctor intake-detail route contract + ownership refusal
- `npm run test:unit:frontend` - workspace tabs, transcript/playback render, parity
- `npm run typecheck`

## Handoff notes

- The health of the doctor read mirrors `get_doctor_pre_summary`'s assigned-partner predicate; the media bytes come from the existing stream route, no new upload/stream surface.
- `IntakeDetailView.transcript` / `MediaRefView` already carry everything the tab needs - the work is exposing them on the doctor side and rendering them.
- Prototype `case-workspace.html` §6.2a is the binding visual spec for the pre-summary tab.
