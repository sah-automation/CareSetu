# Brief - T07 Operator MFA login + bootstrap + invite

**Ticket:** #250 · **Parent:** #243 · **Refreshed:** 2026-08-31
**Reading surface:** ~8.7K tokens (budget 10K) - within budget

## Scope

Operator is a trusted closed group, never self-registers. Implement:

- MFA-bound operator login in the iam module (MFA schema fields already on `iam_identities` from #244)
- Bootstrap operator provisioned at deploy time (seed)
- Operator invitation flow (credentialed, MFA-bound at first login)
- The `operator` role grant so `require_operator` (already in `app/gateway/rbac.py`) admits them
- Tests mirroring `test_iam_session.py` / `test_iam_verify.py`

Acceptance criteria: see #250 body verbatim.

## Read-list (in order)

1. `apps/backend/app/gateway/rbac.py` - `require_operator` dependency already exists, confirms the scope-gating contract this ticket activates (~0.3K)
2. `apps/backend/modules/iam/schema/models.py` - `iam_role_grants` table with role constraint `('patient','partner','operator')`, `iam_identities` table with MFA fields from #244 (~1.1K)
3. `apps/backend/modules/iam/session_facade.py` - `issue_session` pattern (phone lookup -> role grant resolve -> mint JWT) to adapt for operator scope; `_resolve_active_role` helper (~3.7K)
4. `apps/backend/modules/iam/identity_facade.py` - `register_patient` begin-or-resume pattern (ON CONFLICT, emit event, issue challenge) to adapt for bootstrap operator provisioning (~1.8K)
5. `apps/backend/modules/iam/facade.py` - coordinator delegation surface, role grant observable methods from #248 (~2.1K)

## Do NOT read

- `apps/backend/modules/iam/adapters/routes.py` (route infrastructure only, no operator routes yet)
- `apps/backend/scripts/seed_demo.py` (patient seed, different concern)
- `apps/backend/bus/events.py` (no new operator events in this ticket)
- Other module code, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (operator session/verify tests green)
- `npm run typecheck`
- `npm run migration-check`

## Handoff notes

- `require_operator` in `rbac.py:54` is already wired - this ticket provides the identity/role/session plumbing that makes it reachable.
- Bootstrap operator: provisioned at deploy via a seed script or test-seed endpoint (pattern: `seed_demo.py` but with operator role grant instead of patient). The operator identity gets an `Active` role grant for `operator` at seed time.
- Operator login reuses the existing register -> verify OTP -> issue session flow, but the session scope resolves to `operator` instead of `patient`. The `_resolve_active_role` helper in `session_facade.py:361` already queries `iam_role_grants` by role - just pass `"operator"` instead of `"patient"`.
- Invitation: a credentialed operator (existing operator session) invites a new phone; the invited identity is created and given a pending/MFA-bound state until first login completes MFA.
- Blocking: #244 (MFA schema fields) and #245 (partner identity) must land first so MFA fields exist on `iam_identities` and the operator role grant constraint is active.
