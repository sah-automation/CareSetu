# Fix Plan: Operator Login Bugs B and C

## Context

Issue #294 (role-aware `/v1/me` + operator refresh scope) was implemented and confirmed working (no more 403 on `/v1/me`). Two remaining bugs in the operator login flow need fixing:

- **Bug B:** Wrong TOTP code shows no error message - silently transitions to MFA re-entry step
- **Bug C:** No redirect to `/operator` after successful login - form returns to initial state with values preserved, no error banner

---

## Bug B: Wrong TOTP code shows no error message

### Root cause

The backend raises `OperatorMfaError` for **all** failure cases:

1. MFA not enrolled (`session_facade.py:214-218`)
2. No TOTP secret (`session_facade.py:235-239`)
3. Wrong TOTP code (`session_facade.py:240-246`)

The exception handler at `routes.py:418-425` maps **all** of them to HTTP 401 with code `SESSION_MFA_REQUIRED`.

The frontend at `StaffLoginForm.tsx:170-179` catches `SESSION_MFA_REQUIRED` and transitions to the MFA re-entry step (sets `mfaContext`, clears TOTP, focuses TOTP input). So when the user enters a wrong code on first submit, the form silently transitions to the MFA step instead of showing an error. On the MFA step (`StaffLoginForm.tsx:142-144`), a wrong code triggers `setNotice(envelopeNotice(error))` which calls `staffOperatorErrorCopy` which shows `t.genericError` ("Something went wrong on our side.") - not a specific "wrong code" message.

### Fix: Backend

**File: `apps/backend/modules/iam/domain/exceptions.py`**

Add a new exception class after `OperatorMfaError` (line 50-60):

```python
class InvalidOperatorCodeError(IamError):
    """The TOTP code presented during operator login failed verification (S9, #262).

    Distinct from ``OperatorMfaError`` which signals missing MFA enrollment.
    This is an authentication failure the frontend must surface as a
    user-visible "wrong code" message rather than transitioning to the MFA
    re-entry step.
    """
```

**File: `apps/backend/modules/iam/session_facade.py`**

At lines 240-246, change the `except` block to raise `InvalidOperatorCodeError` instead of `OperatorMfaError`:

```python
# Current (line 243-246):
except (TotpSecretEmptyError, TotpVerificationError, ValueError) as exc:
    raise OperatorMfaError(
        f"TOTP verification failed for identity {identity_id}: {exc}"
    ) from exc

# Fixed:
except (TotpSecretEmptyError, TotpVerificationError, ValueError) as exc:
    raise InvalidOperatorCodeError(
        f"TOTP verification failed for identity {identity_id}: {exc}"
    ) from exc
```

Add import at top of `session_facade.py`:

```python
from modules.iam.domain.exceptions import InvalidOperatorCodeError
```

Keep `OperatorMfaError` for lines 214-218 and 235-239 (missing enrollment / no secret) - those are correct as-is.

**File: `apps/backend/modules/iam/adapters/routes.py`**

1. Add import (line 32-41):

```python
from modules.iam.domain.exceptions import (
    IamError,
    InvalidOperatorCodeError,  # ADD
    InvalidPhoneError,
    ...
)
```

2. Add exception handler (after `_operator_mfa_failed` at line 418-425):

```python
async def _invalid_operator_code(request: Request, exc: Exception) -> JSONResponse:
    return error_response(
        status.HTTP_401_UNAUTHORIZED,
        "INVALID_OPERATOR_CODE",
        "Invalid authentication code. Please try again.",
        log_tag="iam_rejection",
        request=request,
    )
```

3. Register handler (line 486, after the `OperatorMfaError` handler):

```python
app.add_exception_handler(InvalidOperatorCodeError, _invalid_operator_code)
```

Note: `InvalidOperatorCodeError` inherits from `IamError`, so it must be registered **before** the catch-all `IamError` handler (line 490). FastAPI matches the most specific handler first, but registering it earlier is defensive.

### Fix: Frontend

**File: `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx`**

At lines 170-183, update the `.catch()` handler to treat `INVALID_OPERATOR_CODE` as a displayable error, not a state transition:

```typescript
.catch((error: unknown) => {
  if (
    error instanceof ApiError &&
    error.code === "SESSION_MFA_REQUIRED"
  ) {
    // MFA not enrolled - transition to TOTP re-entry step
    setMfaContext({ masked: maskPhone(rawPhone), raw: rawPhone });
    setTotpCode("");
    setFieldErrors({});
    setNotice(null);
    setTimeout(() => totpRef.current?.focus(), 0);
  } else if (
    error instanceof ApiError &&
    error.code === "INVALID_OPERATOR_CODE"
  ) {
    // Wrong TOTP code - show error, stay on same step, re-focus TOTP
    setNotice(envelopeNotice(error));
    setTotpCode("");
    setTimeout(() => totpRef.current?.focus(), 0);
  } else {
    setNotice(envelopeNotice(error));
  }
})
```

**File: `apps/frontend/src/components/auth/staff/staffLoginState.ts`**

Update `staffOperatorErrorCopy` (lines 108-123) to handle the new code:

```typescript
export function staffOperatorErrorCopy(
  error: unknown,
  t: LoginStrings,
): string {
  if (error instanceof ApiError) {
    switch (error.code) {
      case "INVALID_CREDENTIALS":
        return t.invalidCredentials;
      case "ACCOUNT_LOCKED":
        return t.accountLocked;
      case "INVALID_OPERATOR_CODE":
        return t.invalidOperatorCode; // NEW
      default:
        return t.genericError;
    }
  }
  return t.genericError;
}
```

**File: `apps/frontend/src/lib/i18n/dictionaries.ts`**

Add `invalidOperatorCode` string to the EN staff auth login section (after `genericError` at line 116):

```typescript
invalidOperatorCode: "Invalid authentication code. Please try again.",
```

Add the same to the HI dictionary.

**File: `apps/frontend/src/components/auth/staff/staffLoginState.ts`**

Update `StaffAuthStrings` type import (or the inline type) to include `invalidOperatorCode`. Check the `StaffAuthStrings` interface in `dictionaries.ts` and add the new field.

---

## Bug C: No redirect to `/operator` after successful login

### Root cause (hypothesis - needs validation)

The flow is:

1. `operatorLogin({ phone, code })` succeeds -> returns `SessionResult`
2. `.then((session) => landAfterLogin(session))` is called
3. `landAfterLogin` calls `completeStaffLogin(session)` which calls `fetchMe(session.jwt)` then `saveSession(session, me.phone)`
4. `router.push(postLoginTarget({ surface: "staff", roles: me.roles }))` is called

If `fetchMe` fails, a plain `Error` is thrown (not `ApiError`) and caught by `.catch()` which shows `envelopeNotice(error)` -> `t.genericError`. But the user reports **no error banner**.

If `fetchMe` succeeds and `router.push` is called, the navigation should work. But the user reports the page stays on the login form.

**Most likely explanation:** After `saveSession` writes to localStorage and `router.push("/operator")` navigates, the `AuthProvider` (root layout) re-renders with `user: null` (its initial state). The AuthContext's mount `useEffect` already ran and read the **old** session (before `saveSession` wrote the new one). When the operator page renders, AuthContext has `user: null` and `isLoading: false`. The `StaffLoginView` useEffect (`page.tsx:50-68`) sees `isLoading: false`, `isAuthenticated: false`, and returns early - no redirect. But the operator page itself (`app/(operator)/operator/page.tsx`) likely doesn't have an auth guard, so it renders fine.

Wait - that contradicts the user report. Let me reconsider.

**Alternative explanation:** `router.push` IS working, the page navigates to `/operator`, but then the AuthContext immediately calls `router.replace("/staff/login")` because it sees `user: null`. The operator page renders momentarily then bounces back.

**Check:** Does the `useAuth()` hook or any layout guard redirect unauthenticated users? The `(operator)` layout (`app/(operator)/layout.tsx`) is an `AppShell`. If it or any child checks `useAuth()` and redirects when `!isAuthenticated`, that would explain the bounce.

**Investigation steps:**

1. Open browser DevTools Network tab
2. Enter phone + correct TOTP, submit
3. Confirm `POST /v1/auth/operator/login` returns 200
4. Confirm `GET /v1/me` returns 200 with `roles: ["operator"]`
5. Watch for any redirect responses (302/307) or additional `GET /v1/me` calls
6. Check Console for any errors

**Fix options (ordered by likelihood of success):**

### Option 1: Force full page reload after login (most reliable)

In `landAfterLogin` (`StaffLoginForm.tsx:106-109`), replace `router.push` with a full page navigation to ensure AuthContext re-initializes from localStorage:

```typescript
async function landAfterLogin(session: SessionResult) {
  const me = await completeStaffLogin(session);
  // Full page load ensures AuthContext re-reads session from localStorage
  window.location.replace(
    postLoginTarget({ surface: "staff", roles: me.roles }),
  );
}
```

### Option 2: Update AuthContext state after login

After `saveSession`, also update the AuthContext's `user` state directly. This requires either:

- Passing a callback from AuthContext to the login form
- Using a custom event / broadcast channel to notify AuthContext
- Importing and calling `setUser` from a shared module

More complex but avoids a full page reload.

### Option 3: Check for redirect guards

Investigate whether the `(operator)` layout or `AppShell` has an auth guard that redirects back to `/staff/login` when `user` is null. If so, that guard needs to handle the "session just saved, AuthContext not yet updated" case.

**Recommended approach:** Start with **Option 1** (full page reload). It's the simplest and most reliable. Optimize to Option 2 later if the full reload causes UX issues (e.g., flash of loading state).

---

## Implementation order

1. **Bug B first** - it's a clean backend+frontend change with clear root cause
2. **Bug C second** - needs investigation during implementation, may require Option 1 or deeper fix

## Files to modify

### Bug B

| File                                                         | Change                                                                       |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| `apps/backend/modules/iam/domain/exceptions.py`              | Add `InvalidOperatorCodeError` class                                         |
| `apps/backend/modules/iam/session_facade.py`                 | Import new exception; raise it at line 244 instead of `OperatorMfaError`     |
| `apps/backend/modules/iam/adapters/routes.py`                | Import new exception; add handler `_invalid_operator_code`; register handler |
| `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx` | Handle `INVALID_OPERATOR_CODE` in `.catch()`                                 |
| `apps/frontend/src/components/auth/staff/staffLoginState.ts` | Add `INVALID_OPERATOR_CODE` case to `staffOperatorErrorCopy`                 |
| `apps/frontend/src/lib/i18n/dictionaries.ts`                 | Add `invalidOperatorCode` string (EN + HI)                                   |

### Bug C

| File                                                         | Change                                                                   |
| ------------------------------------------------------------ | ------------------------------------------------------------------------ |
| `apps/frontend/src/components/auth/staff/StaffLoginForm.tsx` | Replace `router.push` with `window.location.replace` in `landAfterLogin` |

## Verification

- Run `npm run test:unit:backend` after Bug B backend changes
- Run `npm run test:unit:frontend` after frontend changes
- Run `npm run lint` and `npm run typecheck` for both
- Manual E2E: login with wrong TOTP -> should show "Invalid authentication code" error
- Manual E2E: login with correct TOTP -> should redirect to `/operator`
