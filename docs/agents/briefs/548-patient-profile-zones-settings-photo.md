# Brief - 548 Patient profile Identity + Settings zones + photo UI

**Ticket:** #548 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The patient profile becomes a professional three-zone page (US-24, US-25): **Identity** (name/age/gender/language/area/photo with upload/preview/remove), **Health background** (placeholder in this ticket - filled by the next ticket), and **Settings** - notification preferences, default language, consent management (surface the patient's existing consent grants with revoke, and the ability to revoke a `health_background` grant), and data export/delete leads marked clearly as coming soon. The photo upload UI hands the session photo to the backend photo endpoint and shows the stored photo; every new string EN/HI; desktop and mobile.

AC:

- [ ] Profile page reorganized into Identity / Health background / Settings zones, preserving existing profile fields and save flow (idempotency kept)
- [ ] Photo upload/preview/remove wired to the photo endpoint and rendered from the stored key; remove clears it
- [ ] Settings: notification prefs, default language, consent management (grants list + revoke incl. `health_background`), export/delete leads marked coming soon
- [ ] EN/HI parity; component tests + `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The existing patient profile page `app/(patient)/patient/profile/page.tsx` + its test - the current single-card form being reorganized into zones, its save flow and idempotent PUT to preserve (~1.5K).
2. The profile state/client seams: `ProfileContext` (`finishProfile`, `useOptionalProfile`), `lib/profile/api.ts` (GET/PUT `/v1/me/profile` incl. `photo_ref`), `profileState.ts` (`seedDraftFromServer`, `draftToProfilePayload`) - what the zones reuse unchanged (~1K).
3. The photo endpoint contract from #533 (PUT/DELETE own-photo on `/v1/me/*`, validation rejects, streamed reads) + the photo upload/preview/remove component pattern (~0.5K).
4. The consent client: `lib/consent/api.ts` grants list + `revokeConsent`, and the `consent-log` page's grant/revoke sheet UI to mirror in Settings (~1.2K).
5. The i18n `profile`/`patientHome` dictionary blocks + parity test for all new copy (~0.5K).
6. The chrome Profile entry (already live for patients in `NAV_CONFIG.patient`) - how the profile page is reached today (~0.3K).

## Do NOT read

- Backend internals beyond the /v1/me and consent API contracts, doctor console pages, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-09-24 (1288 passed, 89 files).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - profile zones/photo/settings/consent tests + parity green.
- `npm run typecheck` - clean.

## Handoff notes

- Requires #533 landed (photo endpoint). The Health background zone is a placeholder here - #549 fills it.
- The profile save flow and idempotent PUT semantics are preserved; the reorganization is presentational plus the photo control and the new Settings zone.
- Navigate a `health_background` grant appears in the grants list like any other scope (necessary so it can be revoked); the revoke must work for it exactly like the others.
- Data export/delete are copy-only "coming soon" leads - no backend work, no dead buttons beyond a disabled/marked state.
- No em-dashes anywhere (lint-gated); use simple dashes.
