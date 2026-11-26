# Brief - 261 Phase-5 fix: genuine TOTP verification in operator login (S8 · US-15)

**Ticket:** #261 · **Parent:** #243 · **Refreshed:** 2026-09-01
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

`issue_operator_session` gates on `_mfa_verified` but the MFA secret is never genuinely TOTP-verified at login (finding S8, US-15 "operator MFA"). Add real TOTP verification: at login, require the operator to present an RFC-6238 TOTP code derived from their stored secret and check it against the current window. This is the missing step in an already-present MFA scaffolding.

Acceptance criteria (from #261):

- [ ] `issue_operator_session` requires a TOTP code from the client and verifies it against the stored `iam_operator_mfa.secret`.
- [ ] TOTP verification window/tolerance matches the standards (RFC-6238 with a small drift window, refusing TOCTOU/replay in the accepted window).
- [ ] Existing US-15 MFA/invite tests extend, not replace; a wrong/expired code is rejected.

## Read-list (in order)

1. `apps/backend/modules/iam/session_facade.py` - `issue_operator_session` (~158) and `_mfa_verified` (grep it around the session gate; find where the MFA gate short-circuits today), plus `issue_partner_session` for the surrounding pattern. Read the whole session gate region plus lines 380-580 for the role/mfa helpers (~2K).
2. `apps/backend/modules/iam/schema/models.py` - the `iam_operator_mfa` table: `secret` (encrypted), `mfa_enabled` bool, `last_verified_at`, unique on `identity_id`. Show how the secret is stored/encrypted today (is it already doing `encrypt`? confirm the KMS/fernet path) (~0.8K).
3. `apps/backend/modules/iam/facade.py` - `record_mfa_verified` (176-184), `issue_operator_session` (192-198), `create_operator_account` (148-162) for the invite->verify->login flow and the `operator.invited`/`operator.mfa` event bus (bus/events.py:51) (~1K).
4. `apps/backend/modules/iam/domain/exceptions.py` - existing session/MFA exceptions to reuse (`SessionError`/MFA-specific) (~0.5K).
5. `docs/spec/phase-5-partner-onboarding.md` - US-15 operator MFA + login requirements, and the existing PHASE-5-T07 brief (`docs/agents/briefs/` - operator MFA/invite) which nailed the module shapes; read the T07 brief for the invitation flow it already described (~1.5K).

## Do NOT read

- notify/audit/partner provider internals (S4/S5 overlap), `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`

## Done-verify (acceptance criteria -> commands)

- US-15 / operator MFA tests green (grep tests for `issue_operator_session` / `mfa` and run them + full unit suite)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Handoff notes

- The scaffolding exists: `iam_operator_mfa` table with encrypted `secret` + `_mfa_verified` gate + `record_mfa_verified`. What's MISSING is the actual TOTP check at login - the gate is currently satisfied without a presented code. That is the review gap (S8).
- This ticket is the TOTP-verify part; the invite/enroll/`record_mfa_verified` write path is the existing T07 brief (#250) work that already landed. Do not rebuild enrollment.
- `iam/facade.py` and `session_facade.py` names: an operator login might be `issue_operator_session(code=...)` taking the TOTP code. Keep the existing `require_operator` RBAC seam in `app/gateway/rbac.py` untouched.
- Unit tests on this repo use the `_FakeResult`/`_FakeScalar` mock idiom for rowcount/scalar reads - follow it, and do NOT sleep real time; inject a clock/pyotp time for window math (the repo injects `clock` elsewhere, e.g. CircuitBreaker).
- Check whether pyotp / an RFC-6238 impl is already a dependency; if not, add it to `pyproject.toml` (extend existing test). Keep secrets handling per security-phii-standards (no plaintext secret in logs; decrypt at verify time only).
