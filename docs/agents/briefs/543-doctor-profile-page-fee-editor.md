# Brief - 543 Doctor profile page + fee editor move

**Ticket:** #543 · **Parent:** #529 · **Refreshed:** 2026-09-24
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

A doctor can open their own Profile page from the chrome (avatar entry point) and see and edit the private projection: photo upload/preview/remove, practice details, experience, languages, about, availability, notifications, and the consultation fee - whose editor moves here from the dashboard landing (US-26, US-27, US-28). The page shows a public-directory preview link for the read-only public entry, and the verified/credential-status display. The "Profile" nav entry goes live with this page. All copy EN/HI; desktop and mobile.

AC:

- [ ] Profile nav entry live (un-sooned with config + test) and the page renders the full private projection
- [ ] The consultation-fee editor now lives here (moved off the landing) and saves through the unchanged fee path
- [ ] Photo upload/preview/remove hits the profile-media-backed endpoint; a public-directory preview link is shown (read-only)
- [ ] EN/HI parity; component tests + `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. The doctor profile API shape from #542 (private GET/PUT contract, photo endpoint, `provider_profile` read model) - the data the page renders and edits (~0.5K).
2. The fee path client: `updateConsultationFee` in `lib/partner/api.ts` (+ `fetchPartnerMe`) - the unchanged fee seam the moved editor calls (~0.5K).
3. The chrome avatar entry point from #538 (the `AccountMenu` doctor trigger) - the surface the Profile page opens from (~0.4K).
4. `components/dashboard/nav-config.ts` + test - un-soo the doctor Profile entry the same way #541 does Patients (~1K).
5. The photo-upload component precedent - the patient photo UI from #548 if landed, else the `ProfileCompletionWizard` file-intent + `Avatar` photoRef precedence to mirror for upload/preview/remove (~0.6K).
6. UI form primitives + the i18n `doctorConsole`/`profile` dictionary block + parity test (~0.8K).

## Do NOT read

- Backend internals beyond the API contract from #542, `docs/archive/`, the doctor Patients page internals.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-09-24 (1288 passed, 89 files).
- `npm run lint`, `npm run typecheck` - confirmed green 2026-09-24.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend` - profile page/nav/photo/fee-editor tests + parity green.
- `npm run typecheck` - clean.

## Handoff notes

- Requires #542 landed; the fee route contract is unchanged, only its editing surface moves from the landing to this page (the landing keeps a summary card in #544).
- Photo upload/preview/remove flows through the profile-media-backed private endpoint from #542; the key is rendered via the `Avatar`/photo stream, never a public URL.
- Public-directory preview is a read-only link to the unchanged public projection - no editing surface this batch.
- Nav un-soo mirrors #541; both flip doctor-chrome entries that #538 left `soon`.
- No em-dashes anywhere (lint-gated); use simple dashes.
