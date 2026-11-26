# Brief - 272 Phase-5 review fix: MFA TOTP enrollment endpoint + bootstrap seed (P1, US-15)

**Ticket:** #272 · **Parent:** #243 · **Refreshed:** 2026-09-02
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

The `iam_operator_mfa` row is written with `secret=""` (a schema-placeholder), and `generate_secret()` / `encrypt_secret()` exist in the domain but are never called from any production path. At operator login, `issue_operator_session` calls `decrypt_secret("", key)`, which raises (empty base64 fails the length check) and is wrapped as a 401 - so no operator, including the bootstrap operator from `seed_demo.py`, can ever complete MFA login. This is the review gap P1 (critical, US-15 "operator MFA").

Add a real TOTP enrollment path so the secret column gets a genuine encrypted value, and fix the bootstrap seed to produce one too.

Acceptance criteria (from #272):

- [ ] `POST /v1/auth/operator/mfa/enroll` endpoint exists, returns `{ secret, provisioning_uri }` for the authenticated operator.
- [ ] `MfaFacade.enroll_mfa()` calls `generate_secret()` + `encrypt_secret()` and stores the encrypted blob in `iam_operator_mfa.secret`.
- [ ] `record_mfa_verified()` no longer writes `secret=""`.
- [ ] `scripts/seed_demo.py` generates a real encrypted TOTP secret for the bootstrap operator.
- [ ] Operator can complete full flow: invite -> enroll MFA -> login with TOTP code.
- [ ] Unit tests for `enroll_mfa()` and an integration test for invite-enroll-login round-trip.
- [ ] Existing tests pass (`node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`, `npm run typecheck`).

## Read-list (in order)

1. `apps/backend/modules/iam/facade.py` - the public `record_mfa_verified` (178) delegating to `self._mfa`, and how `IamFacade` is constructed with `mfa_secret_key` (103, 129). This is the facade seam the new `enroll_mfa` should mirror. (~1.2K)
2. `apps/backend/modules/iam/mfa_facade.py` - `record_mfa_verified` (60-118): the `secret=""` placeholder, the upsert on `identity_id`, and `VerifyMfaResult`. New `enroll_mfa` lives here. (~1.5K)
3. `apps/backend/modules/iam/domain/totp.py` - `generate_secret()` (79) and `verify_totp()`; the provisioning URI / pyotp API available. (~0.6K)
4. `apps/backend/modules/iam/domain/secret_encryption.py` - `encrypt_secret()` (42) and `decrypt_secret()` (54), plus `_decode_key` / required key bytes. (~0.6K)
5. `apps/backend/app/config.py` + `app/main.py` - `iam_mfa_secret_key` (config 129/347; main 146) - how the MFA key is injected into the facades; the enroll route must access the same key. (~0.8K)
6. `apps/backend/modules/iam/adapters/routes.py` - `operator_login` (348-380) and `OperatorLoginRequest` (111-120) for the existing operator route + auth dependency pattern (`require_operator` / `require_*`), and `_error_response` (383-405) the error envelope helper. (~1.5K)
7. `apps/backend/scripts/seed_demo.py` - `_seed` (73-93) bootstrap path calling `record_mfa_verified`. (~0.5K)
8. `docs/spec/phase-5-partner-onboarding.md` - US-15 + operator MFA requirements; existing PHASE-5-T07 brief (`docs/agents/briefs/`) which described the invite flow. (~1.2K)
9. Tests: `tests/unit/test_totp.py`, `tests/unit/test_secret_encryption.py`, `tests/integration/test_iam_operator_mfa.py` (note its `_enroll_mfa_secret` helper that does a raw SQL `UPDATE` - the pattern the production enroll should replace).

## Do NOT read

- partner/notify/audit module internals, `docs/archive/`, frontend.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `tests/unit/test_totp.py`, `tests/unit/test_secret_encryption.py`, `test_iam_operator_mfa.py` (integration) green; new enroll/logon round-trip tests green
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- The category of reviewers' finding is "incomplete MFA enrollment": the gate (`_mfa_verified` in `session_facade`) passes (mfa_enabled + last_verified_at set) but verification always fails against the empty secret - a split-brain posture. Fixing enrollment makes login actually work; do NOT tear down the gate.
- `seed_demo.py` currently calls `facade.record_mfa_verified(...)` which persists `secret=""`. After this ticket, seeding should persist a real encrypted secret (or enroll then record) so the bootstrap operator can log in. Consider whether seed should print/hint the provisioning URI for the dev to enroll their authenticator.
- The `enroll_mfa` facade method should mirror the existing `record_mfa_verified` delegation shape in `iam/facade.py`. Keep the secret encrypted per security-phii-standards; never log or return plaintext beyond the single enroll response.
- The app builds `SessionFacade` with `mfa_secret_key` (main.py:146). The enroll route needs the same key to encrypt. Reuse `encrypt_secret(secret, key)` where key comes from the same config the session facade already consumes.
- Follow the repo's `_FakeResult` / `_FakeScalar` mock idiom in unit tests; do not sleep real time - pyotp time/window can be controlled for determinism.
- Parent for all Phase-5 review-fix briefs is #243 (the Phase-5 spec). This ticket's proposals were drawn from the code-review finding P1.
