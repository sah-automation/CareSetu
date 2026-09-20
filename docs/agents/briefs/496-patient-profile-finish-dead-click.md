# Brief - 496 PHASE-8.1 T14: patient profile Finish dead click after fresh OTP login (identity resolution + never-silent save)

**Ticket:** #496 · **Parent:** #479 · **Refreshed:** 2026-09-20
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Frontend-session fix for the dead Finish click after a fresh OTP login (root cause: session provider validates only on mount; patient OTP flow persists the session then navigates client-side, so session state holds no identity; the profile provider mounts without identity, hydration is skipped, and Finish silently returns false).

What to build, per the ticket:

1. **Session-resume seam (auth module):** a seam the patient OTP flow invokes immediately after persisting a new session. It re-runs the existing identity-resolution path (the same `/v1/me` read used on reload) with the freshly stored JWT and applies the resolved identity and roles to session state. Reuses the existing resolution path - no decoding client-side, no new API contract, no backend change, and NO reload introduced anywhere in the login path.
2. **Never-silent save invariant (patient profile module):** Finish resolves only through a successful profile write (PUT), or an explicit, visible failure. The two silent-return branches in `finishProfile` (identity absent; required basics incomplete) become status-writing branches that surface the existing bilingual save-error copy before resolving false. The completion host and inline gate stay controlled widgets: they render the shared save-status notice and route to the dashboard only on success.
3. **Draft storage:** in-flight draft stays keyed by identity id; the legacy unscoped fallback key becomes unreachable in a logged-in session once identity resolution is guaranteed. No migration of legacy unscoped drafts.

Tests required by the ticket:

- **Seam 1 (unit, fast, deterministic):** profile-completion host composed with the patient profile provider. Three cases: identity resolved + complete basics (persists via PUT and routes), identity unresolved (surfaces visible save error, never silent), incomplete basics (surfaces visible save error). Regression gate for the silent no-op.
- **Seam 2 (e2e):** fresh patient journey on the live backend + mock SMS: register phone, complete OTP, land on dashboard, open profile-completion page, fill required basics, advance to Finish, click Finish - no page reload anywhere in the chain. Assert URL becomes the dashboard, the profile PUT succeeded, and the account identity resolves post-login (masked phone visible in the account menu).

## Read-list (in order)

1. `lib/auth/AuthContext.tsx` (209 lines) + `lib/auth/session.ts` (92 lines) + `lib/auth/api.ts` - the session provider: mount-only `validate()` effect (L110-179), `fetchMe`/`applyMe`/`MeResponse` (uses `identity_id`), `saveSession`/`readSession`/presence-hint cookie. Where the resume seam + context method go (~1.5K tokens)
2. `components/auth/otp/otpState.ts` (`submitOtp` L254-338, `saveSession` call L278) + `components/auth/otp/PatientAuthWizard.tsx` (redirect effect L307-311, `DoneStep` L223-254) - where the seam is invoked after persisting a session, before client-side routing (~900 tokens)
3. `lib/profile/ProfileContext.tsx` (184 lines) - `ProfileProvider` `key={user?.id ?? "anon"}` (L80), hydration effect deps `[identityId]` (L100-139, skips when identity undefined), `finishProfile` (L150-167) with the two silent-return branches to convert (~800 tokens)
4. `lib/profile/profileState.ts` (`draftStorageKey` L226-230 identity-scoped / unscoped fallback, `basicsComplete` L97-105, `draftToProfilePayload` throw path) + `lib/profile/api.ts` (`getProfile`/`saveProfile` PUT with Idempotency-Key, throws `ApiError`) (~700 tokens)
5. Hosts/notice: `app/(patient)/patient/profile/complete/page.tsx` (`handleFinish` L25-32), `components/patient/profile/SaveStatusNotice.tsx` (error `data-testid="profile-save-error"`), `components/patient/profile/ProfileGate.tsx` (`handleFinish` L58-62), `components/patient/profile/ProfileCompletionWizard.tsx` (`goNext` L73-83, finish button) - the controlled host/gate rendering behavior (~500 tokens)
6. i18n: `lib/i18n/dictionaries.ts` `profile.save` block (en L652-659, hi L1682-1687) + `lib/i18n/dictionaries.test.ts` parity gate (~250 tokens)
7. Unit test seams (prior art): `lib/profile/ProfileContext.test.tsx`, `app/(patient)/patient/profile/complete/page.test.tsx`, `lib/auth/AuthContext.test.tsx`, `components/auth/otp/PatientAuthWizard.test.tsx` - the `vi.hoisted` + `vi.mock` patterns, `state.user` escape hatch, `/v1/me` fetch spies (~1.5K tokens)
8. E2E seams (prior art): `tests/e2e/auth-loop.spec.ts` (helpers L80-152, fresh-login assertions L297-328) + `tests/e2e/patient-journey.spec.ts` + `playwright.config.ts` (env for mock SMS + live backend) (~1.2K tokens)
9. `docs/adr/0007-split-origin-deployment-session-invariants.md` - hard gate: this touches session/login flow (auth module); split-origin vs localhost masking (~1K tokens)

## Do NOT read

- Backend: `/v1/me/profile` routes, iam facade, schema - unchanged, out of scope.
- Doctor console, care module, pick-doctor flow, `lib/auth/staff` flows (they share the same session gap but #496 is patient-OTP scoped), `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - passes with exactly 1 known pre-existing failure: `src/app/page.test.tsx` EN/Hindi homepage parity (Daltonganj string, per prior briefs).
- `npm run typecheck` - passes.
- Note: `src/app/(doctor)/doctor/cases/[caseId]/page.test.tsx` stage-chip test is flaky (timeout on a cold run, passes on rerun) - not caused by this work.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - Seam 1 three-case host+provider tests, resume-seam unit coverage, existing suites still green
- `npm run typecheck`
- `npm run test:e2e` - Seam 2: fresh patient journey, Finish persists (PUT) and lands on `/patient` with identity in the account menu, no reload anywhere (needs backend env, see `tests/integration/README.md` and `playwright.config.ts`)

## Handoff notes

- #482 and #488 are merged (commits `1aed6f2`, `01965a8`); profile paths verified unchanged since #488.
- Two `/v1/me` response shapes coexist in `lib/auth`: `AuthContext.MeResponse` uses `identity_id`; `api.ts` `MeResult` uses `subject_id`. The resume seam must use `AuthContext`'s existing `fetchMe` path, not decode client-side.
- Key insight for wiring the seam: `ProfileProvider` keys on `user?.id ?? "anon"` and hydration is dep-driven on `identityId`, so once the seam applies identity, the provider remounts and hydrates - a reload is never needed even if the seam resolves slightly after route change.
- The save-error copy already exists bilingual (`profile.save.error`); the seam-2 account-menu assertion is new (no existing e2e asserts masked phone). `AccountMenu` shows full phone in `identityLine` and last-2-digits in the avatar trigger.
- ADR-0007: end-to-end seam must be re-run against the deployed split-origin topology before closeout, not trusted on localhost alone.
