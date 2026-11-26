# Brief - 294 Fix operator login 403 at GET /v1/me - role-aware /v1/me + operator refresh scope

**Ticket:** #294 · **Parent:** operator login session bug (diagnosed from a local repro) · **Refreshed:** 2026-09-04
**Reading surface:** ~7K tokens novel (budget 10K) - within budget, two seams + test retargets

## Scope

Make `GET /v1/me` answer any authenticated principal (patient/partner/operator) so an operator login no longer 403s on the frontend's post-login `/v1/me` session check, and fix the refresh-token rotation so a stored operator/partner session rotates to the same scope instead of being re-minted as patient (which clears the session on reload).

- [ ] `/v1/me` `GET` admits any authenticated principal and returns its resolved roles (role-aware)
- [ ] the `patient` / `operator` / `partner` role guards stay intact on their own routes
- [ ] refresh-token rotation re-derives scope from the session row's recorded scope (operator/partner survive reload)
- [ ] Backend tests: operator token on `/v1/me` -> `200` `roles:["operator"]`; gateway 403 access-denial coverage preserved on a role-guarded seam; operator-refresh rotation test added
- [ ] Frontend: no code change required; verify both `/v1/me` call sites succeed for operators

## Read-list (in order)

1. **RBAC dependency set** - `require_patient`, `require_operator`, `require_partner` and the scope-resolution helper, in the gateway's RBAC module (`app/gateway/rbac.py`). Each rejects anonymous/missing callers with 401 and authenticated-but-wrong-role with 403 via the gateway exception types. You add an `authenticated`-only dependency here alongside them. (~1 inline read)
2. **`GET /v1/me` route + `MeResponse`** - the protected session-read route in the FastAPI app shell (`app/main.py`). It currently declares the patient guard; change it to the new `authenticated` guard. `MeResponse` already carries `subject_id`, `roles`, `phone` - no shape change. (~1 inline read)
3. **`refresh_session` + scope helpers** - in the iam session sub-facade (`modules/iam/session_facade.py`). `refresh_session` re-derives the rotated scope with a `patient`-only helper call deep in its rotate branch, and `_resolve_active_role(connection, identity_id, role)` resolves an identity's active grant for a given role. The `iam_sessions` row shape stores the minted `scope` column. Read the rotate branch and the two helpers. (~2 inline reads)
4. **Gateway error + 403 access-denial emit** - `AuthenticationRequiredError`, `InsufficientScopeError`, and the authenticated-403 audit emit (`patient.auth_failed`, reason `access_denied`) in the gateway errors module. The 401 path is what the new `authenticated` dependency reuses; the 403 audit emit stays on the role-guarded routes. (~1 inline read)
5. **Test surfaces** (read relevant slices only):
   - Gateway unit tests (`tests/unit/test_gateway.py`) - the app-level `client` helper that swaps in a facade stub for `/v1/me`, the `issue_token`/scope test helper, the `200 patient` admission test, and the three `/v1/me`-based 403 access-denial tests (they use an unknown `superadmin` scope).
   - IAM access-denial integration test (`tests/integration/test_iam_access_denial.py`) - the 403-writes-`patient.auth_failed`-to-outbox test, which also uses `superadmin` scope against `/v1/me`.
   - `/v1/me`-adjacent app-shell and contract tests (`test_app_shell.py`, `test_contract_check.py`) - confirm they are unauthenticated/CORS-only and unaffected.
6. **Frontend verify context (no edit)** - the staff login form's post-login completion and the root auth/session bootstrap both fetch `/v1/me` with the access JWT (`components/auth/staff/StaffLoginForm.tsx` `completeStaffLogin`, `lib/auth/AuthContext.tsx` bootstrap). The operator login returns an operator-scoped session; these calls must get `200 roles:["operator"]`.

## Do NOT read

- The OTP demo-mode / mock-SMS config area and its three tests (`test_app_shell` dev-otp gating, mock-SMS production-default, `test_seed_demo` OTP-surface description) - they fail PRE-EXISTING from an unrelated uncommitted config change; not part of this ticket.
- The partner / audit route modules in full - only needed to pick a role-guarded 403 retarget seam.
- i18n dictionaries, the other frontend API clients (beyond the two `/v1/me` call sites).
- `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - expect exactly the 3 pre-existing config failures above, everything else green.
- `npm run typecheck`
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - new `authenticated` / operator `/v1/me` / operator-refresh tests green; the 3 pre-existing config failures remain the only failures.
- `npm run typecheck` - no new type errors.
- `npm run lint` - clean.
- Frontend confirm (if a regression test is added): `npm run test:unit:frontend`.

## Key decisions to reconcile

- `authenticated`-dependency semantics: admit any authenticated principal (unknown scope -> `roles: []`, `200`) vs. only principals with at least one known role. Recommendation: admit any authenticated principal - simplest, and real tokens always resolve a known role. Keep the existing fail-closed scope resolution unchanged.
- `/v1/me` no longer 403s for any authenticated caller, so the gateway 403 access-denial audit path must keep coverage on a role-guarded seam - retarget the 3 unit + 1 integration access-denial tests to an `operator`/`partner` role-guarded route (or a role-guarded probe route in the unit client). Keep the 403 audit emit behavior; do not weaken it.
- `refresh_session` scope re-derive: resolve the identity's active grant for the session row's recorded `scope` (falling back to patient if that role grant is gone), rather than trusting the stored scope blindly and rather than hard-coding patient.

## Handoff notes

- The frontend bug is real but the fix is backend-only: once `/v1/me` admits operators, the staff login form's post-login completion and the auth bootstrap both work. Frontend unit tests mock `/v1/me`, which is why the bug hid - add a red-capable test only if a clean seam exists (an API/integration/contract test asserting an operator token gets `200` from `/v1/me`).
- The three backend access-denial 403 unit tests and the one integration test all use the unknown `superadmin` scope against `/v1/me`. After the change, `superadmin` on `/v1/me` returns `200 roles: []` - do not keep using `/v1/me` for the 403-audit seam.
- The `iam_sessions.scope` column is populated with the minted scope at session creation, so it is a reliable source for the refresh re-derive.
- Commit only this ticket's files; leave the unrelated uncommitted `config.py` / frontend wizard changes already in the working tree untouched.
