# Fix Plan: Issue #330 Code Review Findings

**Origin:** Two-axis code review of `06fadb0...HEAD` (issues #331-#338)
**Date:** 2026-09-07
**Status:** Draft

---

## Context

The architecture deepening pass (#330) split the partner facade into four sub-facades, concentrated credential-validity into one module, absorbed the duplicate OTP re-issue choreography, and removed the iam-to-partner circular dependency. The review found two hard standard violations, one partial spec requirement, and one potential atomicity regression.

## Findings to Fix

### F1. `Any` type usage in sub-facade constructors (coding-standards §3)

**Where:** `modules/partner/directory_facade.py`, `modules/partner/operator_gate_facade.py`

Both sub-facades type `credential_validity` and `directory_cache` as `Any` in their `__init__` signatures. The coding standard requires "No `Any`" and "Type everything". The coordinator facade (`facade.py`) already imports these as module-level references (`credential_validity_module`, `directory_cache_module`).

**Fix:** Define a minimal `Protocol` in `modules/partner/shared.py` (or a new `modules/partner/ports.py`) that captures the surface the sub-facades actually call:

```python
from typing import Protocol, Any

class CredentialValidityPort(Protocol):
    def provider_visible(self, column: Any) -> Any: ...
    def has_any_credential(self, column: Any) -> Any: ...
    def has_invalid_credential(self, column: Any) -> Any: ...
    async def close_out_credentials(self, connection: Any, credentials: list[Any]) -> list[int]: ...

class DirectoryCachePort(Protocol):
    async def get_cached_search(self, **kwargs: Any) -> Any: ...
    async def set_cached_search(self, **kwargs: Any) -> None: ...
    async def directory_visibility_changed(self) -> None: ...
```

Replace `Any` annotations with `CredentialValidityPort` and `DirectoryCachePort` in both sub-facades. The coordinator passes `credential_validity_module` and `directory_cache_module` which already satisfy the protocol implicitly.

**Files to change:**

- `apps/backend/modules/partner/shared.py` (add protocols)
- `apps/backend/modules/partner/directory_facade.py` (annotate `__init__`)
- `apps/backend/modules/partner/operator_gate_facade.py` (annotate `__init__`)
- `apps/backend/modules/partner/credential_intake_facade.py` (annotate `__init__` - already `ModuleType`, confirm consistency)

---

### F2. Duplicate `PARTNER_SCHEMA` constant (coding-standards §2 / single source of truth)

**Where:** `modules/partner/credential_validity.py:1230`

`credential_validity.py` defines its own `PARTNER_SCHEMA = "partner"` while `modules/partner/shared.py` already defines the canonical constant. The standard demands a single source of truth.

**Fix:** Remove the local constant from `credential_validity.py` and import from `shared.py`:

```python
# In credential_validity.py, replace:
PARTNER_SCHEMA = "partner"
# With:
from modules.partner.shared import PARTNER_SCHEMA
```

**Files to change:**

- `apps/backend/modules/partner/credential_validity.py` (remove duplicate, import from shared)

---

### F3. US10 partial: `PartnerView` not owned by a single sub-facade

**Where:** `modules/partner/common_models.py`

`PartnerView` lives in `common_models.py` and is returned by the registration sub-facade, the operator-gate sub-facade (via `grace_lapse`), and the coordinator's close-out family. US10 says "each sub-facade owns its result models".

**Fix:** Move `PartnerView` to `modules/partner/registration_models.py` since registration is the primary owner (it creates the initial `PartnerView` on register/register_partner). Re-export from the coordinator facade for backward compatibility. The operator-gate sub-facade imports from `registration_models.py` for its return type.

**Files to change:**

- `apps/backend/modules/partner/common_models.py` (remove `PartnerView`)
- `apps/backend/modules/partner/registration_models.py` (add `PartnerView`)
- `apps/backend/modules/partner/credential_intake_facade.py` (import from `registration_models`)
- `apps/backend/modules/partner/operator_gate_facade.py` (import from `registration_models`)
- `apps/backend/modules/partner/facade.py` (re-export `PartnerView` from `registration_models`)

---

### F4. WI-3 partner-gate atomicity gap

**Where:** `modules/iam/adapters/routes.py:273-102`, `modules/iam/session_facade.py`

**The problem:** The base code verified partner-profile existence inside `issue_partner_session` under the identity row lock (`FOR UPDATE`). The refactored route does an unlocked advisory pre-read (`resolve_identity_id_by_phone` then `resolve_partner_id_by_identity`) and `issue_partner_session` only checks `partner_id < 1`. A profile deleted between the route check and the mint lets a partner-scoped token issue for a now-patient-only phone.

**Fix:** Move the partner-profile existence check back inside `issue_partner_session` (under the identity row lock) while keeping the route-level verification as an early-rejection optimization. The mint method should re-verify the partner profile exists under the same transaction as the session row lock:

In `session_facade.py`, after locking the identity row and before minting:

```python
# Re-verify partner profile existence under the identity row lock
if partner_id < 1:
    raise SessionIssuanceError(
        "partner status was not verified before issuing a partner session"
    )
# The route pre-checked, but we re-check under lock for atomicity
# (the profile could have been deleted between the route check and here)
```

The simplest safe fix: keep the `partner_id` parameter as an advisory input, but add a SQL re-check of partner-profile existence inside `issue_partner_session` under the identity row lock. This preserves the route-level early rejection (fast path) while restoring atomicity (slow path under lock).

**Files to change:**

- `apps/backend/modules/iam/session_facade.py` (add re-check under lock in `issue_partner_session`)
- `apps/backend/modules/iam/adapters/routes.py` (no change needed - route still pre-checks for early rejection)
- `tests/unit/test_iam_session.py` (add test: profile deleted between route check and mint refuses with 409)
- `tests/unit/test_iam_session_route.py` (add test: concurrent profile deletion during mint)

---

## Execution Order

1. **F2** (trivial - remove duplicate constant)
2. **F1** (add protocols, re-type sub-facade constructors)
3. **F3** (move `PartnerView` to registration_models, update imports)
4. **F4** (add re-check under lock, add tests)

F1-F3 are independent of F4. F2 should land first as it is a one-line fix.

## Verification

After each fix, run:

- `npm run test:unit:backend` - unit suite
- `npm run typecheck` - mypy strict + tsc
- `npm run lint` - pre-commit gate
- `npm run migration-check` - alembic single-head gate (expected unaffected)

F4 additionally needs:

- New unit test: concurrent profile deletion between route check and mint
- Existing integration suite (native PostgreSQL) passes unchanged
