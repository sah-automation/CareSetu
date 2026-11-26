# Brief -- T2 Partner registration submission

**Ticket:** #280 -- **Parent:** phase5-frontend-gap-plan -- **Refreshed:** 2026-09-03
**Reading surface:** ~8K tokens (budget 10K) -- within budget (focus on submit handler only)

## Scope

Wire the existing 4-step provider registration wizard (`ProviderRegisterWizard.tsx`) to actually submit applications to the backend. On final submit: call `POST /v1/partner/register` then `POST /v1/partner/credentials` (with base64-encoded artifacts from the upload slots). On success: create session, route to `/partner/status/pending` via `postLoginTarget`. On error: display the shared `ErrorEnvelope` with trace id. Existing local validation (`providerRegisterState.ts`) stays as-is.

## Read-list (in order)

1. `apps/frontend/src/components/auth/staff/ProviderRegisterWizard.tsx` -- focus on: final submit handler (~line 805-808, currently `setNotice(t.phase5Notice)`), `WizardValues` type (line 46 import), `UPLOAD_SLOTS` (line 29), form state shape. Skip: individual step components (StepAccountBasics, StepIdentity, StepCredentials, StepReview) -- they export their own rendering, the root only owns state + gating. (~918 lines but most is step rendering, read selectively)
2. `apps/frontend/src/components/auth/staff/providerRegisterState.ts` -- `WizardValues` type definition, `UPLOAD_SLOTS` mapping (per partner type), `normalizeApplicationType`, `validateStep` (to understand what's already validated client-side)
3. `apps/frontend/src/lib/partner/api.ts` -- T1 output: `registerPartner(body)`, `submitCredentials(body)` functions
4. `apps/frontend/src/lib/auth/api.ts` -- `SessionResult` interface (jwt, jti, scope, identity_id, expires_in_seconds, refresh_token)
5. `apps/frontend/src/lib/auth/session.ts` -- `saveSession(session, phone)` signature; `StoredSession` shape
6. `apps/frontend/src/lib/auth/staff-routing.ts` -- `postLoginTarget(input)` signature, `PostLoginInput` interface, `PartnerStatusState` type

## Do NOT read

- operator pages, patient pages, backend dispatcher, docs/archive/, prototype/, `lib/record/api.ts`, `lib/consent/api.ts`.

## Baseline verify (must pass before the first edit)

- `npm run test -w @caresetu/frontend`
- `npm run typecheck -w @caresetu/frontend`
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend` -- no regressions (existing wizard tests must still pass)
- `npm run typecheck -w @caresetu/frontend` -- no type errors
- `npm run lint` -- no lint violations

## Handoff notes

- **T1 dependency**: `lib/partner/api.ts` must exist before this ticket starts. Import `registerPartner` and `submitCredentials` from it.
- The submit handler is at line 805-808 in the current code. Replace `setNotice(t.phase5Notice)` with the real submit flow.
- The wizard collects: `fullName`, `email`, `password`, `mobile` (Step 1); identity fields (Step 2); `UPLOAD_SLOTS[type]` file slots (Step 3); declarations (Step 4). The `WizardValues` type holds all of these.
- `POST /v1/partner/register` body: `{ phone, partner_type, practice_name?, practice_address, practice_latitude, practice_longitude, service_area_id? }`. The wizard currently collects some of these fields -- check what's missing and either add fields or use defaults.
- `POST /v1/partner/credentials` body: `{ credentials: [{ credential_type, artifacts: ["base64..."] }] }`. The wizard stores uploads as `File` objects -- convert to base64 before sending.
- After both calls succeed, call `saveSession(sessionResult, phone)` to persist the session, then `window.location.href = postLoginTarget({ surface: "staff", roles: [...], partnerState: "pending" })` to route.
- The error notice pattern: use `{ kind: "envelope", message: envelope.message, traceId: envelope.trace_id }` to display errors. The existing `Notice` type in StaffLoginForm is a good reference.
- The wizard's `mobile` field is optional in the current form but the backend requires `phone`. Ensure the phone is collected (it may come from Step 1 `mobile` or a new required field).
