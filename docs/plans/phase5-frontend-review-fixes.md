# Phase 5 - Frontend Review Fixes Plan

**Status:** ready for `/to-tickets`
**Source:** Two-axis code review (Standards + Spec) of `git diff c937fc3...HEAD` (Phase-5 FE #278-#285).
**Upstream targets:** `docs/standards/coding-standards.md` §9 (config, no hardcode) + §8 (readability) + REQ-006 i18n, `docs/standards/api-standards.md` §2 (error envelope) + §5 (idempotency), `docs/standards/ai-engineering-standards.md` §B2 (i18n single source), `docs/plans/phase5-frontend-gap-plan.md` (parent feature plan).

## Scope

Nine fix findings from the two-axis review of the Phase-5 FE slice (#278-#285). Frontend only, no backend changes. Each fix maps to a review finding below.

### Standards-axis findings

1. Hardcode of country code `91`/`+91` in `normalizePhone` (`ProviderRegisterWizard.tsx`)
2. Hardcode of `practice_latitude: 0` / `practice_longitude: 0` in the wizard submit
3. Hardcoded `POLL_INTERVAL_MS = 10_000` in both partner status screens (config, not code)
4. Hardcoded English strings in doctor landing + wizard (i18n/REQ-006 breach)
5. Duplicated fetch wrapper + `isPartnerView` across `partner/api.ts`, `operator/api.ts`, `audit/api.ts`
6. Duplicated `TYPE_BADGE`/`STATUS_BADGE` maps in operator queue list + detail + inconsistent status keys
7. Dead `mfaEnrolled` slot in `StaffLoginForm` alongside the real TOTP flow

### Spec-axis findings

8. Wrong implementation - `#282` MFA field sends the password value as the TOTP `code` parameter
9. Wrong implementation - `#281` pending screen renders `decision_reason` as the "Verifying scope"

Out of scope (judgement calls / partial, deferred or accepted): `#279` doctor name not shown (session has no name field - accept phone display), `#285` decision navigate-back has no explicit cache-bust (acceptable), `#284` extra client-side sort toggles (accepted behaviour), `#284` client-side sort vs server-side (accepted), `#285` audit timeline + verification history table (accepted scope), `RecordPage` client-side sort (Feature Envy, mild - accepted).

## Fix 0 - shared `request<T>` fetch helper + shared type guards

**Standards finding 5.** The three API clients (`partner/api.ts`, `operator/api.ts`, `audit/api.ts`) each replicate the NETWORK_ERROR-catch + `parseErrorEnvelope` + shape-guard pattern, and `isPartnerView` is redefined in both `partner/api.ts` and `operator/api.ts`.

- `apps/frontend/src/lib/api-base.ts` (or new `apps/frontend/src/lib/request.ts`):
  - Add `request<T>(path, options?): Promise<unknown>` - one helper that wraps `authedFetch`, catches network failure -> `ApiError NETWORK_ERROR`, parses the error envelope on non-ok, returns the parsed JSON payload.
  - Add `guardShape<T>(data: unknown, isT: (v: unknown) => v is T, unexpectedMessage: string): T` - throws `ApiError UNEXPECTED_ERROR` when the shape guard fails.
- `apps/frontend/src/lib/partner/api.ts`, `operator/api.ts`, `audit/api.ts`: replace the local `partnerFetch`/`operatorFetch`/inline try-catch with `request<T>`; replace the local `UNEXPECTED_ERROR` throw blocks with `guardShape`. Move `isPartnerView` to a single shared location (e.g. `lib/partner/api.ts` and re-export, or a `lib/shapes.ts`).
- Tests: keep existing contract tests green; add one test for `request<T>` network/error-envelope/shape paths in `lib/api-base.test.ts` (or the new module's test).

## Fix 1 - move wizard phone + practice-geo constants out of code

**Standards finding 1 + 2.**

- `apps/frontend/src/components/auth/staff/ProviderRegisterWizard.tsx`:
  - `normalizePhone`: stop hardcoding the `91`/`+91` country code. Read the country code from `NEXT_PUBLIC_*` config (e.g. `NEXT_PUBLIC_DEFAULT_COUNTRY_CODE`) with a dev/CI-safe default in `.env.example`. Normalize only the user-supplied digits and let the backend's phone validation be authoritative (mirror the wizard's existing "server stays authority" comment).
  - Wizard submit: remove the hardcoded `practice_latitude: 0, practice_longitude: 0`. **Backend constraint (confirmed):** `partner/schema/models.py:69-70` makes both columns `nullable=False` and `partner/adapters/routes.py:82-83` require them with `Field(ge=-90,le=90)` / `(ge=-180,le=180)`. So the fields are mandatory and approach (a) - dropping them - is **not** viable without a backend change. Use approach (b): add an explicit geolocation step/stub the user fills (or derives from the selected service area's known coords), never send silent `0,0`. Raise a separate backend ticket only if a truly optional lat/long is desired (out of scope here - this plan is frontend-only).
- `.env.example`: document `NEXT_PUBLIC_DEFAULT_COUNTRY_CODE` with a non-secret default.
- Tests: update any wizard test asserting the hardcoded `91` prefix / `0,0` coords; keep the normalize behavior for the default config.

## Fix 2 - poll interval to config

**Standards finding 3.** `POLL_INTERVAL_MS = 10_000` appears in both `partner/status/pending/page.tsx` and `partner/status/rejected/page.tsx`.

- Add `NEXT_PUBLIC_STATUS_POLL_INTERVAL_MS` (default `10000`) to `.env.example` + frontend config (single source of truth, per §9.2). Read it once (e.g. in a shared `lib/poll.ts` or `lib/config.ts`) and use in both screens.
- Tests: no change beyond ensuring both screens read from the shared constant.

## Fix 3 - move doctor-landing + wizard strings into i18n dictionaries

**Standards finding 4.** Doctor landing (`(doctor)/doctor/page.tsx`) and the wizard hardcode English strings, bypassing the bilingual `STRINGS` dictionary used by every other screen.

- `apps/frontend/src/lib/i18n/dictionaries.ts`: add the missing keys under the existing `doctor` and `staff`/`register` sections (both `en` and `hi`): doctor welcome, next-steps bullets, wizard submitting/error copy, "Phone number is required", "Trace: " prefix, and any other surfaced string.
- `apps/frontend/src/app/(doctor)/doctor/page.tsx` + `ProviderRegisterWizard.tsx`: replace hardcoded English with dictionary lookups via the existing i18n mechanism.
- Tests: add/extend dictionary shape tests; ensure the doctor page renders from `t` and the wizard maps error copy through the dictionary (mirror how `staffOperatorErrorCopy`/`staffLoginErrorCopy` centralize error copy).

## Fix 4 - shared badge maps + consistent status keys

**Standards finding 6.** `TYPE_BADGE`/`STATUS_BADGE` maps are byte-identical in `(operator)/operator/page.tsx` and `(operator)/verification/[partner_id]/page.tsx`; status keys are inconsistent (`"Under Verification"` mixed-case vs `verified`/`rejected` lowercase).

- Extract to a shared module (e.g. `apps/frontend/src/components/operator/badges.ts` or `lib/partner/status.ts`): one `STATUS_BADGE`/`TYPE_BADGE` map + a `statusKey(status: string)` normalizer that maps backend status strings to stable lowercase keys.
- Update both operator pages to import from the shared module; replace any raw-string key lookups with the normalizer. This also fixes the primitive-obsession inconsistency (finding 6c).
- Tests: add a unit test for `statusKey` covering every backend status value; keep both screens' tests green.

## Fix 5 - remove the dead `mfaEnrolled` slot from `StaffLoginForm`

**Standards finding 7.** The form still carries the inert `mfaEnrolled` slot ("never functional this phase") alongside the now-real TOTP MFA flow.

- `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx`: delete the `mfaEnrolled` dead slot and any now-unused state/strings; keep the real `SESSION_MFA_REQUIRED`-driven TOTP step. If the flag is genuinely referenced elsewhere, route the surviving flow through the real MFA step only.
- `staffLoginState.ts` + dictionaries: drop any now-unused `mfaEnrolled` copy.
- Tests: update `StaffLoginForm.test.tsx` / `staffLoginState.test.ts` to remove assertions on the dead slot; keep the real MFA-step coverage.

## Fix 6 - align operator login with the actual backend protocol

**Spec finding 8 (wrong implementation, #282).** The review flagged that `StaffLoginForm.tsx:158` calls `operatorLogin({ phone, code: password })` - sending the password field value as the `code` parameter on the first submit. On `SESSION_MFA_REQUIRED` it switches to a real TOTP step (`StaffLoginForm.tsx:137`).

**Backend protocol (verified this session):** `iam/adapters/routes.py:109-118` `OperatorLoginRequest` has **no password field** - only `{ phone, code }` where `code` must match `pattern=r"^[0-9]{6}$"` (a 6-digit RFC-6238 TOTP, per the docstring at routes.py:117-118). So the first-step "password" is being misused as a TOTP code and will be rejected (`422`, pattern mismatch) whenever the user's password is not exactly 6 digits.

The spec's "Phone + password submit calls `POST /v1/auth/operator/login`" presupposes a password field the backend does not implement. The fix is to align the frontend with the real server contract - the login is phone + TOTP (with `SESSION_MFA_REQUIRED` surfacing the MFA step), not phone + password.

- `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx`:
  - First (phone path) submit should send a valid TOTP `code`, not the password field value. Either (a) treat the first operator submit as already expecting the TOTP code input (drop the password-as-code misuse), or (b) if the `SESSION_MFA_REQUIRED` two-step UX is kept, the first call must still send a real 6-digit TOTP - meaning the "password" field is actually the TOTP field and must be labelled/validated as such.
  - Remove `code: password` (line 158); submit the 6-digit TOTP from the MFA/TOTP field. Keep phone masked and error-envelope handling.
- `apps/frontend/src/lib/operator/api.ts`: `OperatorLoginRequest` is already `{ phone, code }` and `code` is validated client-side as 6-digit - keep it. If the form's first submit no longer needs the password at all on the operator path, gate that path off the password field.
- Confirm with the backend owner whether `SESSION_MFA_REQUIRED` is still emitted (given the route has no password step, the two-step 401 flow may be unnecessary - the client may go straight to the TOTP step on the first submit).
- Tests: update `StaffLoginForm.test.tsx` + `operator/api.test.ts` to assert: operator submit sends a 6-digit TOTP `code` (never the password value), `SESSION_MFA_REQUIRED` still surfaces the TOTP step, and a non-6-digit code is rejected client-side before hitting the API.

## Fix 7 - pending screen renders verification round state, not `decision_reason`

**Spec finding 9 (wrong implementation, #281).** The pending page renders `verification?.decision_reason` in the "Verifying scope" row. `decision_reason` carries the rejection reason from a prior round - semantically wrong for a fresh "Under Verification" application.

- `apps/frontend/src/app/(partner)/partner/status/pending/page.tsx`: replace the `decision_reason` read with the correct field for the current verification round state - `verification.status` (current round status) and any round-appropriate scope/decision only when set for the current round. If the backend view exposes a distinct current-verification-scope field, use it; otherwise drop the row rather than showing a stale prior-round reason.
- Confirm the backend `/v1/partner/me/verification` shape (`PartnerVerificationStatusView` in `lib/partner/api.ts`) - map to the current round's fields only.
- Tests: update `partner/status/pending/page.test.tsx` to assert the pending screen shows the current round status, not a prior `decision_reason`.

## Suggested order & verification

Order: **Fix 0** (shared helper - foundation most files touch) -> **Fix 6** (login protocol - depends on Fix 0 since both touch `operator/api.ts`) -> **Fix 7** (pending scope - independent) -> **Fix 3** (i18n) -> **Fix 1** + **Fix 2** (config/hardcode - independent) -> **Fix 4** (shared badges) -> **Fix 5** (dead slot). Fixes 1, 2, 4, 5, 7 are independent after Fix 0 and can land in parallel PRs; Fix 6 shares `operator/api.ts` with Fix 0 so it should follow it in the same PR.

Verify each with the repo harness (`AGENTS.md`): `npm run test -w @caresetu/frontend`, `npm run typecheck -w @caresetu/frontend`, `npm run lint`. No backend, migration, or integration changes expected.

## Risks

- Fix 6: the backend `OperatorLoginRequest` (routes.py:109-118) has **no password field** - it takes `{ phone, code }` where `code` is `[0-9]{6}` TOTP. The current frontend sends the password value as `code` on the first submit (`StaffLoginForm.tsx:158`), which will 422 unless the password is exactly 6 digits. The fix must align client + server protocol; confirm with the backend owner whether `SESSION_MFA_REQUIRED` is still emitted given there is no password step.
- Fix 1: `practice_latitude`/`practice_longitude` are `nullable=False` (schema) and required `Field` (routes) - the fields cannot simply be dropped; a real user/derived geolocation value is required, not silent `0,0`.
- Fix 3 i18n touches the shared dictionary shape - the existing dictionary-shape tests must stay green and both `en`/`hi` variants must be added together.
