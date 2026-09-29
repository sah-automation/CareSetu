# Brief - 552 Fix three patient profile bugs: photo storage, health background save, height/weight race

**Ticket:** #552 · **Parent:** none · **Refreshed:** 2026-09-26
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Fix three related bugs on the `/patient/profile` page:

1. **Profile photo not persisting to Supabase + avatar not updating** - When a patient uploads a profile photo and saves, the photo is not stored in the connected Supabase `profile-media` bucket. The avatar at the top-right of the desktop screen (in `AccountMenu` and `BottomTabs`) also does not update to reflect the new photo.

2. **Health background save fails with generic error** - When saving the health background for the first time, the patient sees "We could not save your health background. Please try again." instead of the consent interstitial that should appear for the first-save acknowledgment. The backend correctly requires `acknowledge_phi: true` on first save, but the frontend surfaces a generic failure message rather than guiding the user through the consent flow.

3. **Height/Weight measurements show empty state after adding** - After successfully adding a height/weight measurement, the list shows "You have not added any height or weight measurements yet" even though entries exist. This is a race condition: the initial `loadFirstPage()` fetch completes _after_ the optimistic update from `handleAdd()`, overwriting the locally added entry with the server's empty list.

## Read-list (in order)

1. **ProfileContext.tsx** - The shared `useProfile()` context that holds `savedProfile.photo_ref` and exposes `syncPhotoRef(ref)` which updates both `savedProfile` and the local draft. `AccountMenu` and `BottomTabs` read the avatar ref via `useOptionalProfile().savedProfile?.photo_ref`. (~1.2K tokens)

2. **ProfilePhotoCard.tsx** - Uploads photo via `uploadPatientPhoto(file, key)` → PUT `/v1/me/photo`, then calls `onPhotoRefChange(updated.photo_ref)` which is `syncPhotoRef` from the context. The card previews via `fetchPatientPhoto()` (GET `/v1/me/photo`) streaming bytes over authed transport. (~1K tokens)

3. **AccountMenu.tsx** (desktop) - Reads `photoRef={saved?.photo_ref}` from `useOptionalProfile()` and passes to `Avatar` component. The avatar renders the object URL from the streamed bytes. (~0.8K tokens)

4. **BottomTabs.tsx** (mobile) - Reads `photoRef={profile?.savedProfile?.photo_ref}` from `useOptionalProfile()` in the `AccountCard` inside the More sheet. Same `Avatar` primitive. (~0.8K tokens)

5. **HealthBackgroundSnapshotForm.tsx** - `handleSave()` checks `acknowledged` flag from the read; if false, opens consent sheet (`setConsentOpen(true)`). `handleConsentConfirm()` calls `commit(..., true)` → `saveHealthBackground(..., { acknowledgePhi: true })`. The catch block currently treats all errors as generic `snapshotSaveFailed`. Must catch `ApiError` with `code === 'HEALTH_BACKGROUND_ACK_REQUIRED'` and open consent sheet instead. (~1.5K tokens)

6. **HealthBackgroundZone.test.tsx** - Existing test `it("keeps the draft and re-asks when the acknowledged save is refused")` simulates `HEALTH_BACKGROUND_ACK_REQUIRED` rejection and expects the consent sheet to reopen. This test currently passes because the mock rejects with that error code, but the actual component doesn't handle it - the test is testing the _desired_ behavior. Use as reference for the fix. (~1K tokens)

7. **HealthMetricsSeries.tsx** - `handleAdd()` does optimistic update: `setEntries(current => [entry, ...current])`, `setTotal(current => current + 1)`, then clears draft. The initial `loadFirstPage()` (triggered by `useEffect` on mount) races with this. Fix: after successful `appendHealthMetric`, `await loadFirstPage()` to reconcile. Follows the existing `loadMore()` pattern which refetches. (~1.2K tokens)

8. **main.py lines 337-341** - `HealthFacade` composition: `HealthFacade(engine, consent_facade=app.state.consent_facade, care_facade=app.state.care_console_facade)`. Verify both facades are injected for the first-save auto-grant to live-relationship doctors via `_discover_live_relationship_doctors()`. (~0.5K tokens)

9. **routes.py lines 293-302** - `HEALTH_BACKGROUND_ACK_REQUIRED` error handler: returns 422 with code `HEALTH_BACKGROUND_ACK_REQUIRED` and message "the first health-background save must acknowledge that the snapshot becomes visible to your doctors". The frontend must match this code exactly. (~0.3K tokens)

10. **profile/api.ts** - `uploadPatientPhoto`, `fetchPatientPhoto`, `deletePatientPhoto` - thin typed wrappers over `/v1/me/photo` PUT/GET/DELETE. All answer `StoredPatientProfile` with updated `photo_ref`. (~0.5K tokens)

11. **health-background/api.ts** - `fetchHealthBackground`, `saveHealthBackground`, `fetchHealthMetrics`, `appendHealthMetric` - thin typed wrappers. `saveHealthBackground` takes `{ acknowledgePhi, retryKey }`. `appendHealthMetric` takes `HealthMetricInput` and `retryKey`. (~0.5K tokens)

## Do NOT read

- `docs/archive/` - superseded by PRD
- `modules/profile_media/` - Supabase bucket creation is infra/DevOps (out of scope per ticket)
- `modules/iam/facade.py` photo seam - the photo upload endpoint works; the bug is frontend avatar sync, not backend storage
- `modules/consent/` - consent grant logic works; the bug is frontend error handling
- `apps/frontend/src/components/ui/avatar.tsx` - avatar rendering is correct; it reads `photoRef` prop
- Binary assets, migration files, CI configs

## Baseline verify (must pass before the first edit)

```bash
# Backend unit tests for affected routes
node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit/test_health_background_route.py tests/unit/test_health_background_metrics_route.py tests/unit/test_profile_photo_routes.py -q

# Frontend unit tests for affected components (run individually if needed)
npm run test:unit:frontend -- src/components/patient/profile/ProfilePhotoCard.test.tsx
npm run test:unit:frontend -- src/components/patient/profile/HealthBackgroundZone.test.tsx
```

All 56 backend tests pass as of baseline. Frontend tests pass but may timeout in batch; run individually.

## Done-verify (acceptance criteria → commands)

**Bug 1 - Profile photo persists and avatar updates:**

- Upload a photo via `ProfilePhotoCard` → verify `uploadPatientPhoto` returns profile with `photo_ref`
- Verify `AccountMenu` avatar (desktop) shows the new photo: `screen.getByTestId("account-menu").querySelector("img")` has object URL
- Verify `BottomTabs` More-sheet `AccountCard` avatar shows the new photo
- Test: `npm run test:unit:frontend -- src/components/patient/profile/ProfilePhotoCard.test.tsx` + visual check

**Bug 2 - First-save consent flow works:**

- Clear health background (or use fresh patient)
- Fill snapshot form, click Save → consent sheet opens (`ps-hb-consent-sheet` visible)
- Click Confirm → `saveHealthBackground` called with `acknowledgePhi: true`
- Backend returns `acknowledged: true` → subsequent saves send `acknowledgePhi: false` without re-prompting
- Test: existing `HealthBackgroundZone.test.tsx` "keeps the draft and re-asks when the acknowledged save is refused" passes

**Bug 3 - Height/Weight list stays consistent after add:**

- Start with empty metrics list
- Add a measurement via form → entry appears immediately (optimistic)
- Wait for `loadFirstPage()` to complete → entry still present, no empty-state flicker
- Add second measurement → both entries visible
- Test: new vitest test in `HealthBackgroundZone.test.tsx` simulating race (add before initial load resolves)

## Handoff notes

- **From #548 (Profile Photo Card):** The `onPhotoRefChange` → `syncPhotoRef` → context → avatar chain is the intended design. The bug is that `PROFILE_MEDIA_BACKEND=supabase` must be set in Render env (separate from `INTAKE_MEDIA_BACKEND`). The `profile-media` bucket must exist in Supabase as a private bucket with service-role write access. These are infra tasks (out of scope) - the code fix ensures the frontend chain works once infra is ready.

- **From #549 (Health Background Zone):** The first-save consent flow is designed per ADR-0018. The backend stamps `acknowledged_at` on first acknowledged save and auto-grants `health_background` consent to live-relationship doctors (via `ConsentFacade` + `CareConsoleFacade` in `HealthFacade`). The frontend must catch the specific error code and open the sheet - it already has the sheet component and logic, just missing the error-code branch.

- **From #535 (Height/Weight Series):** The race condition only manifests when user adds a measurement before `loadFirstPage()` completes. On slow connections this is common. The refetch fix is idempotent, fast (~25 items), and guarantees correctness. The existing test `test_replayed_idempotency_key_does_not_re_append` verifies append idempotency.

- **Environment variables to verify in Render:**

  - `PROFILE_MEDIA_BACKEND=supabase`
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `PROFILE_MEDIA_KEY` (base64 32-byte AES-256 key)
  - These are separate from `INTAKE_MEDIA_*` counterparts.

- **No schema changes needed:** `iam_patient_profiles.photo_ref` column exists. `health_background_snapshots.acknowledged_at` column exists. `health_background_metrics` table exists.
