# Brief - 522 Profile & Settings page: meter + personal details

**Ticket:** #522 · **Parent:** #520 · **Refreshed:** 2026-09-23
**Reading surface:** ~9.5K tokens (budget 10K) - within budget, tight; keep reads targeted

## Scope

The Profile & Settings page becomes real at the patient profile-settings route (UI blueprint §5.8): a completion meter, and editable personal details (name, age, gender) that pre-fill from the saved patient profile and the identity-keyed draft buffer. Save reuses the existing profile-finish path (idempotent write) with the established basics gate - incomplete basics block the save with a plain explanation - and success/error surface through the bilingual save-status notice. Every new label and message ships in English and Hindi.

Acceptance criteria:

- Route renders the §5.8 layout with a completion meter reflecting the profile
- Name, age, gender pre-fill from saved profile and any in-progress draft
- Save blocked while basics incomplete, with a plain explanation; no partial write
- Save success and error show the bilingual save-status notice
- New strings in both locales (i18n parity test passes); axe scan clean
- Page unit tests added; `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green

## Read-list (in order)

1. Spec #520 - Implementation Decisions (Profile & Settings page, "Complete your profile" gating, frontend-only) + stories 22-23, 26-27, 28, 31 (re-fetch if not held) (~1.5K tokens)
2. `docs/design/ui-blueprint.md` §5.8 (Profile & Settings layout: completion meter, personal details, language, emergency contact, area) and §5.9 gating matrix (~1K)
3. Profile read/write API surface - `getProfile()` / `saveProfile()` with `Idempotency-Key`, `StoredPatientProfile` field names, `ProfileReadResult.set` convention (~1K)
4. The profile context/provider (`ProfileProvider`) - hydration order (draft buffer first, server wins), `updateDraft`, `finishProfile` (its basics gate and save-status never-silent invariants), `useOptionalProfile` (~2K)
5. Profile draft/state helpers - `basicsComplete`, `profileCompleteness`/meter %, `draftStorageKey`, `serverProfileToDraft`/`seedDraftFromServer`, `draftToProfilePayload` (optionals to null) (~2K)
6. Bilingual `SaveStatusNotice` component (testids `profile-save-status` / `profile-save-error`) and the live `MeterBar` completion meter primitive (~0.8K)
7. i18n dictionary structure (`profile`, `nav` surface groups) and the English/Hindi parity test that gates every new key (~0.5K)
8. Prior-art page: the existing profile-completion page test (`page.test.tsx`) for route-level test patterns, mocked profile API at module boundary, lexical scoping of provider mocks (~0.7K)

## Do NOT read

- Account menu, nav config, BottomTabs / More sheet, staff-role surfaces
- Language/emergency-contact/area field work (ticket 523) - leave those sections for the next slice
- Backend code, `docs/archive/`

## Baseline verify (must pass before the first edit)

- `npm run typecheck`
- `npm run lint`
- `npm run test:unit:frontend` - note: 1 pre-existing failure in the doctor case pre-summary test is present on the clean tree at HEAD; unrelated to this ticket

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` with the new page test suite green
- `npm run lint`, `npm run typecheck`
- `npm run migration-check` not needed (frontend-only; no schema work)

## Handoff notes

- Route collision: the page lives at `/patient/profile` sharing a prefix with the first-login wizard at `/patient/profile/complete`; both route through the same identity-keyed draft and `finishProfile`. Do not build a parallel save client - reuse `updateDraft`/`finishProfile`.
- Reuse the existing `MeterBar` meter; do not reintroduce the orphaned `ProfileCompletionMeter` from `ProfileNudges`.
- The save-status convention is never-silent: blocked, failed, and success paths all set `saveStatus` before anything else.
- Baseline unit suite is not fully green at HEAD (1 pre-existing failure) - do not chase it; attribute new failures only to your change.
- Avoid em-dashes and non-ascii punctuation in copy (git hook `no-em-dash gate`).
