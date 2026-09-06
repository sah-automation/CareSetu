# Fix Plan: Partner Registration 409 on `POST /v1/auth/session`

## Context

At partner registration (`/staff/register`), completing the 4-step wizard and clicking "Submit Application" surfaces an error on the final step:

- `POST /v1/auth/session` returns HTTP **409** with envelope code `SESSION_REFUSED`
- The UI shows the generic message **"An unexpected error occurred. Please try again."**

This is a real bug (not a deferred later-phase TODO). It is caused by two distinct problems that combine:

1. **Functional:** the wizard calls the patient-only session endpoint for a partner identity, which the backend always refuses.
2. **Error-handling:** `AuthApiError` is not recognized by the wizard's `instanceof ApiError` catch branch, so the real backend error is masked by generic copy.

The partner onboarding loop is a **Phase 5 deliverable** per `docs/plans/phase5-frontend-gap-plan.md` (acceptance criteria section 6: "on submit the application is created (register -> credentials) and the user lands on the pending status screen"). The backend was supposed to make this work but a required piece is missing.

### Prior uncommitted attempt (must be reconciled - see section "Prior uncommitted fix")

Before this plan, an unplanned, uncommitted edit was made in the working tree that tried to fix this exact symptom but did **not** work, and it bundles three separate concerns. That change MUST be reconciled before implementing this plan (details in the dedicated section below). The key points:

- It moved `issueSession`/`saveSession` to run **before** `submitCredentials` - the ordering change is correct and is absorbed here, but it still called the patient-only `issueSession`, so the 409 never went away.
- It also changed `mobile` to a required field (orthogonal product change).
- It changed `apps/backend/app/config.py` `DEFAULT_APP_ENVIRONMENT` from `production` to `dev` (a real production hazard - must be reverted).

### The missing backend capability

`POST /v1/partner/credentials` (and `/me`, `/me/verification`, `/appeal`) are guarded by `require_partner`
(`app/gateway/rbac.py:86`), which requires the caller to present a JWT whose scope resolves to the `partner` role.

But:

- `create_credential_account` (`modules/iam/identity_facade.py:212`) creates the identity as `[Unverified]` with **no** role grant (grant only lands after operator activation, ADR-0010 / T03 #246).
- `issue_session` (`modules/iam/session_facade.py:106`) requires identity **Active** and an **active `patient` role grant** - both impossible for a fresh partner.

There is no `issue_partner_session` path in the backend (`grep` for it returns zero matches). `session_facade.py` has only `issue_session` (patient) and `issue_operator_session` (operator + MFA). The `phase5-frontend-gap-plan.md` escalation note (section 4) says "If a required backend endpoint is found missing, stop and raise it as a backend ticket instead of inventing one" - this is exactly that case, and the chosen solution is to build the missing backend endpoint.

## Root cause details

### Bug A - functional (backend refuses partner session)

`ProviderRegisterWizard.tsx:937` calls `issueSession(phoneE164)` (`lib/auth/api.ts:129`) which hits `POST /v1/auth/session`.

`SessionFacade.issue_session` (`modules/iam/session_facade.py:106-161`) checks, in order:

1. signing key configured (`_access_token_signing_key`)
2. identity exists for the phone (`_lock_identity_by_phone`)
3. `identity_status == IDENTITY_ACTIVE` (line 139) - **fails** for a fresh `[Unverified]` partner
4. active `patient` role grant (`_resolve_active_role(..., _PATIENT_ROLE)`, line 144) - **fails**, partner has no `patient` grant

Either failure raises `SessionIssuanceError`, mapped by `routes.py:409-416` (`_session_refused`) to HTTP 409 `SESSION_REFUSED`.

### Bug B - error masking (frontend)

`ProviderRegisterWizard.tsx:971-980`:

```ts
catch (err) {
  if (err instanceof ApiError) {           // ApiError from @/lib/api-errors (line 22 import)
    setServerError({ message: err.message, traceId: err.traceId });
  } else {
    setServerError({ message: t.errorsSubmitUnexpected, traceId: "" });  // generic
  }
}
```

`issueSession` throws **`AuthApiError`** (defined in `lib/auth/api.ts:63`), which extends the built-in `Error`, NOT the `@/lib/api-errors` `ApiError`. The `instanceof ApiError` check is false, so the real `SESSION_REFUSED` message is replaced by the generic `errorsSubmitUnexpected` copy.

## Chosen solution

Because the Phase 5 loop requires a partner to submit credentials and view their pending status immediately after registration, the fix is:

- **Backend:** add a partner session-issuance path that mints a **`partner`-scoped** JWT for a registered (not-yet-activated) partner.
- **Frontend:** wire the wizard to that new endpoint, and fix the error-catch so `AuthApiError` surfaces real backend text.

### Security assessment for `partner` scope pre-activation

Every route guarded by `require_partner` is **partner self-service only**, exposing no patient/record data:

- `POST /v1/partner/credentials` - submit own credentials
- `GET /v1/partner/me` - own onboarding status
- `GET /v1/partner/me/verification` - own review status
- `GET /v1/partner/rejection-reason` - own rejection reason
- `POST /v1/partner/appeal` - own one-time appeal

All resolve the partner profile by `account.subject_id` and return only that caller's own record. Granting a freshly-registered partner the `partner` scope therefore exposes exactly the self-service surface a pending partner needs and nothing more. This matches the gap plan's intended loop and does not widen access to patient/operator surfaces.

The new endpoint MUST gate on **partner-profile existence** (not identity `Active` status or role grant), because a fresh registrant has neither. It should refuse identities with no partner profile (prevents a random patient from obtaining `partner` scope).

---

## Backend changes

### 1. `apps/backend/modules/iam/session_facade.py`

Add a new method `issue_partner_session(self, phone: str) -> SessionResult`, modeled on `issue_operator_session` but gated on **partner profile existence** rather than identity status / role grant.

Resolve the profile via the existing partner seam (module isolation rule: iam must not touch the partner schema directly). The `IamFacade` already exposes the `_iam` boundary; route through a thin read that crosses the facade seam. Concretely, `SessionFacade` should accept a callable / dependency `resolve_partner_by_phone(phone) -> partner_id | None` injected at construction (mirroring how the partner facade injects `IamFacade`). If it returns `None`, raise `SessionIssuanceError` ("no partner profile for <masked>; register before issuing a session").

Pseudo:

```python
async def issue_partner_session(self, phone: str) -> SessionResult:
    phone_e164 = normalize_phone(phone)
    if not self._access_token_signing_key:
        raise SessionIssuanceError(
            "access-token signing key is not configured; refusing to issue a session"
        )
    now = self._clock()

    async with self._engine.begin() as connection:
        locked = await _lock_identity_by_phone(connection, phone_e164)
        if locked is None:
            raise SessionIssuanceError(
                f"no identity for {mask_phone(phone_e164)}; "
                "register the phone before issuing a session"
            )
        identity_id = locked.identity_id
        # Gate on partner-profile existence via the injected seam - a patient
        # (no partner profile) must never mint a partner-scoped JWT.
        partner_id = self._resolve_partner_by_phone(phone_e164)
        if partner_id is None:
            raise SessionIssuanceError(
                f"identity {identity_id} has no partner profile; "
                "this is a patient-only phone"
            )
        # NOTE: no identity Active check - a fresh registrant is [Unverified].
        # The partner scopes exposed are self-service only (see security note).
        jti, refresh_token, token = await self._mint_session_row(
            connection, identity_id, _PARTNER_ROLE, now
        )

    return SessionResult(
        jwt=token, jti=jti, scope=_PARTNER_ROLE, identity_id=identity_id,
        expires_in_seconds=self._access_token_ttl_seconds, refresh_token=refresh_token,
    )
```

`_mint_session_row` already stores `scope` in the session row and mints the JWT with `scope` as the role claim, so a `partner` scope flows through `resolve_scope_roles` (`app/gateway/rbac.py:33-35`, `partner` is in `KNOWN_SCOPE_ROLES`) to a `partner` Principal role - exactly what `require_partner` needs.

Add the constructor signature (with `self._resolve_partner_by_phone`):

```python
async def issue_partner_session(self, phone: str) -> SessionResult:
    ...
```

Wire the seam in `IamFacade`/`SessionFacade` construction (composition root) so the session facade can resolve a partner profile by phone through the partner module's `PartnerFacade` (dependency inversion, no cross-schema import).

### 2. `apps/backend/modules/iam/facade.py`

Add delegation:

```python
async def issue_partner_session(self, phone: str) -> SessionResult:
    """Mint a partner-scoped access JWT for a registered partner (PHASE-5 gap fix).

    Delegated to ``SessionFacade``; the session's ``scope`` resolves to
    ``partner`` so the gateway's ``require_partner`` admits the caller for
    self-service (submit credentials, read own status, appeal). Unlike
    ``issue_session`` this does NOT require identity ``Active`` or a role
    grant - a fresh registrant is ``[Unverified]`` with no grant (ADR-0010);
    the gate is instead that a partner profile exists for the phone, keeping
    patients from minting a ``partner``-scoped JWT.
    """
    return await self._sessions.issue_partner_session(phone)
```

### 3. `apps/backend/modules/iam/adapters/routes.py`

Add `POST /v1/auth/partner/session` modeled on `issue_session` (lines 216-249), reusing `_set_jwt_cookie`:

```python
@router.post(
    "/partner/session",
    response_model=SessionResult,
    status_code=status.HTTP_200_OK,
    summary="Issue a partner-scoped session for a registered partner",
)
async def issue_partner_session(
    request: Request,
    body: IssueSessionRequest,   # same { phone } shape
) -> Response:
    """Mint a partner-scoped access JWT for a registered (pre-activation) partner.

    The gap-plan loop needs the partner to submit credentials and read their
    own pending status immediately after registration. The partner identity is
    ``[Unverified]`` with no role grant (ADR-0010), so the standard
    ``POST /v1/auth/session`` (patient-only) always refuses 409 ``SESSION_REFUSED``.
    This endpoint instead gates on the existence of a partner profile for the
    phone and mints a ``partner``-scoped JWT (self-service surface only).
    Identity-state refusals (unknown phone, no partner profile) stay 409
    ``SESSION_REFUSED``.
    """
    facade = cast(IamFacade, request.app.state.iam_facade)
    result = await run_idempotent(
        request, lambda: facade.issue_partner_session(body.phone)
    )
    response = Response(
        content=result.model_dump_json(),
        media_type="application/json",
        status_code=status.HTTP_200_OK,
    )
    _set_jwt_cookie(
        response,
        result.jwt,
        result.expires_in_seconds,
        secure=_is_secure_cookie(request),
    )
    return response
```

The exception already maps `SessionIssuanceError` -> 409 `SESSION_REFUSED` via the existing handler (`routes.py:409-416`), so no new handler is required.

---

## Frontend changes

### 4. `apps/frontend/src/lib/auth/api.ts`

Add a partner session caller next to `issueSession`:

```typescript
export function issuePartnerSession(phone: string): Promise<SessionResult> {
  return post<SessionResult>("/v1/auth/partner/session", { phone });
}
```

### 5. `apps/frontend/src/components/auth/staff/ProviderRegisterWizard.tsx`

**a) Call the partner session endpoint instead of the patient one.**

Replace (lines 937-938):

```ts
const session = await issueSession(phoneE164);
saveSession(session, phoneE164);
```

with:

```ts
const session = await issuePartnerSession(phoneE164);
saveSession(session, phoneE164);
```

Update imports: remove `issueSession` from `@/lib/auth/api`, add `issuePartnerSession` (keeps `saveSession` and `postLoginTarget`).

**b) Fix the error catch to surface `AuthApiError` real text.**

Import `AuthApiError` from `@/lib/auth/api` and extend the catch (lines 971-980):

```ts
} catch (err) {
  if (err instanceof ApiError || err instanceof AuthApiError) {
    setServerError({
      message: err.message,
      traceId: "traceId" in err && typeof err.traceId === "string" ? err.traceId : "",
    });
  } else {
    console.error("[provider-register] unexpected submit error", err);
    setServerError({ message: t.errorsSubmitUnexpected, traceId: "" });
  }
}
```

`AuthApiError` has `code` + `details` but no `traceId` field; fall back to `""` for it (or extend `AuthApiError` to carry `traceId` if the envelope supplies one - see note below).

Optional hardening (recommended): give `AuthApiError` a `traceId` field populated from `envelope.trace_id` in `lib/auth/api.ts` (lines 63-73), so this and other auth surfaces can show the trace consistently. The backend envelope includes `trace_id`.

### 6. `apps/frontend/src/lib/auth/api.ts` - AuthApiError traceId (recommended)

Add `readonly traceId: string;` to `AuthApiError` and set it from `envelope.trace_id` in the constructor. This makes Bug B's fix clean (no `"traceId" in err` dance) and improves operator-login error display too.

---

## Test changes

### 7. `apps/frontend/src/components/auth/staff/ProviderRegisterWizard.test.tsx`

- Change the `vi.mock("@/lib/auth/api")` to provide `issuePartnerSession` (mocked to resolve a `SessionResult`) instead of `issueSession`.
- Update the "calls registerPartner then issueSession then saveSession on successful submit" test (line 458) to assert `issuePartnerSession` is called with the E.164 phone, `saveSession` is called once, and `postLoginTarget` is called with the pending partner state.
- Add a test: when `issuePartnerSession` rejects with an `AuthApiError` carrying `SESSION_REFUSED`, the server-error box shows the backend message (not the generic `errorsSubmitUnexpected`). This locks down Bug B.

### 8. `apps/backend` unit tests

Add a test for the `SessionFacade.issue_partner_session`:

- Given an existing identity with a partner profile, it returns a `SessionResult` whose `scope == "partner"` (regardless of `Unverified` identity status / missing role grant).
- Given a phone with no partner profile, it raises `SessionIssuanceError` (409 `SESSION_REFUSED`) - a patient must not mint a partner JWT.
- Given an unknown phone, it raises `SessionIssuanceError`.

Add a route test (mirror `tests/unit/test_iam_session_route.py`) for `POST /v1/auth/partner/session` verifying 200 + `Set-Cookie` on success and 409 `SESSION_REFUSED` for a patient-only phone.

---

## Prior uncommitted fix - reconciliation (do this FIRST)

An unplanned, uncommitted change set exists in the working tree that attempted this exact fix but did not work and bundles unrelated, partly hazardous edits. **Reconcile it before any other work** so the 409 fix lands as a clean, single-purpose change and the work tree is a known state.

Current working-tree state (`git status --short` / `git diff --stat`):

```
 M apps/backend/app/config.py                                            (concern 3 - REVERT)
 M apps/frontend/src/components/auth/staff/ProviderRegisterWizard.test.tsx
 M apps/frontend/src/components/auth/staff/ProviderRegisterWizard.tsx      (concern 1 - KEEP, rework)
 M apps/frontend/src/components/auth/staff/providerRegisterState.test.ts
 M apps/frontend/src/components/auth/staff/providerRegisterState.ts        (concern 2 - SPLIT)
 M apps/frontend/src/lib/i18n/dictionaries.ts
```

### Concern 1 - wizard session ordering (`ProviderRegisterWizard.tsx`)

What it did: moved `const session = await issueSession(phoneE164); saveSession(session, phoneE164);` from AFTER `submitCredentials` to BEFORE it, and removed the `if (!phone)` submit guard in `handleSubmitPartner`.

Why it did not fix the bug: it still called `issueSession` -> `POST /v1/auth/session`, the **patient-only** endpoint, so a partner sees 409 `SESSION_REFUSED` regardless of ordering.

Verdict: KEEP the reordering (credentials need a JWT first), but in this plan's implementation it becomes `issuePartnerSession` (sections 4-5). The new code already places session issuance before `submitCredentials`, so this working-tree edit is superseded - discard it and rely on the plan's final sequence.

### Concern 2 - mobile is now required (`providerRegisterState.ts` + tests + i18n)

What it did: made the `mobile` field required (added `mobileRequired` validation + copy, removed the "alerts optional" wording, removed the `errorsSubmitPhoneRequired` submit guard, updated tests in tandem).

Verdict: ORTHOGONAL to the 409 fix. It is internally consistent and low-risk, but it is a product-behavior change, not a bug fix. **Split it out** so the 409 fix is one coherent change set. Decide explicitly: (a) commit mobile-required as its own change before/after the 409 fix, or (b) revert those edits. Recommendation: (a) as a separate commit.

### Concern 3 - `apps/backend/app/config.py`: `DEFAULT_APP_ENVIRONMENT = "dev"` (REVERT - real hazard)

What it did: changed the default fallback for `APP_ENVIRONMENT` from `"production"` to `"dev"`.

Why it is a hazard: `Settings.app_environment` defaults to `os.environ.get("APP_ENVIRONMENT", DEFAULT_APP_ENVIRONMENT)` (`config.py:282`). In any deploy where `APP_ENVIRONMENT` is not explicitly set, this now boots the app in dev/test mode, which (`config.py:152-157`, `178-183`, `224-230`):

- REFUSES the real SMS/WhatsApp providers (gated to staging/production)
- Treats the app as a dev/test environment in `validate` / `is_demo_or_dev`

If this line ships and a prod/staging deploy is missing the env var, SMS silently stays on mock and the app runs in the wrong environment - a silent production regression.

Verdict: **REVERT immediately** - restore `DEFAULT_APP_ENVIRONMENT = "production"`. If the intent is a local-dev convenience, set `APP_ENVIRONMENT=dev` in a local `.env` instead; never change the committed default. Verify with `git diff apps/backend/app/config.py` that it is clean before proceeding.

### Reconciliation order

1. Revert `config.py` (concern 3).
2. Decide + split the mobile-required change (concern 2) into its own commit or revert it.
3. Discard the working-tree wizard ordering edit and apply the plan's final `issuePartnerSession` sequence (concern 1).
4. Verify the tree contains only this plan's intended changes before committing.

---

## Files to modify

### Revert / reconcile (prior uncommitted fix)

| File                                                                                                 | Change                                                         |
| ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- |
| `apps/backend/app/config.py`                                                                         | REVERT `DEFAULT_APP_ENVIRONMENT` to `"production"` (concern 3) |
| `apps/frontend/src/components/auth/staff/providerRegisterState.ts` + `.test.ts` + i18n + wizard test | Split out or revert the mobile-required change (concern 2)     |

### Backend

| File                                                                                              | Change                                                                |
| ------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------- |
| `apps/backend/modules/iam/session_facade.py`                                                      | Add `issue_partner_session`; inject a `resolve_partner_by_phone` seam |
| `apps/backend/modules/iam/facade.py`                                                              | Add `issue_partner_session` delegation                                |
| `apps/backend/modules/iam/adapters/routes.py`                                                     | Add `POST /v1/auth/partner/session` route                             |
| `apps/backend` composition root (`app/main.py` or wherever `IamFacade`/`SessionFacade` are wired) | Inject the partner-profile resolver seam into `SessionFacade`         |
| Backend test files (`tests/unit/test_iam_session_route.py` + new session_facade test)             | Cover new endpoint + facade                                           |

### Frontend

| File                                                                      | Change                                                                   |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `apps/frontend/src/lib/auth/api.ts`                                       | Add `issuePartnerSession`; (recommended) add `traceId` to `AuthApiError` |
| `apps/frontend/src/components/auth/staff/ProviderRegisterWizard.tsx`      | Call `issuePartnerSession`; fix error catch for `AuthApiError`           |
| `apps/frontend/src/components/auth/staff/ProviderRegisterWizard.test.tsx` | Update mocks/assertions; add `AuthApiError` error-surface test           |

---

## Verification

- **Prior-fix reconciliation first:** `git diff apps/backend/app/config.py` is empty (default restored to `"production"`); the mobile-required change is in its own commit (or reverted); `git diff` shows only this plan's intended changes.
- Regression test for Bug B: `issuePartnerSession` rejecting with `AuthApiError` => server-error box shows the backend message, not the generic `errorsSubmitUnexpected`.
- `npm run test:unit:backend` (new session tests green)
- `npm run test:unit:frontend` (wizard suite green)
- `npm run lint` and `npm run typecheck`
- Manual: run backend + frontend, seed demo DB, complete the wizard => should land on `/partner/status/pending` (was previously stuck at the 409 generic error).
- Read `docs/adr/0007-split-origin-deployment-session-invariants.md` before finalizing the cookie handling on the new route (split-origin vs localhost).

## Post-mortem: what would have prevented this

- The `phase5-frontend-gap-plan.md` assumed a partner session would "just work" after registration without specifying the endpoint; the implementer reused the patient `issueSession`, which can never succeed for a partner. A fatal-seam check (does each `require_partner`-guarded route have a way to be reached by a fresh partner?) would have caught it.
- Two frontend error classes (`ApiError` vs `AuthApiError`) live in different modules and are not mutually recognizable, which silently hid the real backend error behind generic copy. Consolidating error classes (or a shared `isApiError` guard) would prevent this class of masking.
- The prior uncommitted attempt was a "move the call and hope" change that never touched the actually-wrong endpoint. It also mixed an unrelated product change and a hazardous default flip into the same tree - a reminder to keep bug fixes single-purpose and to never change committed security-relevant defaults (like `DEFAULT_APP_ENVIRONMENT`) for local convenience.
