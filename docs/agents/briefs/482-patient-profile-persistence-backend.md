# Brief - 482 Patient profile persistence backend

**Ticket:** #482 · **Parent:** #479 · **Refreshed:** 2026-09-19
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

Server-side persistence of the patient's profile-completion data so a returning patient is asked only once. Adds MOD-001 `iam.patient_profiles` (one row per identity, no cross-schema FKs), `save_patient_profile`/`get_patient_profile` on the identity facade (idempotent upsert), and `PUT/GET /v1/me/profile` (`require_authenticated`-gated). `GET /v1/me` unchanged. Backend only.

AC:

- [ ] `iam.patient_profiles` row persists one row per identity (name, age, gender, preferred_language, area, emergency_contact, nullable photo ref), no cross-schema FKs
- [ ] `PUT /v1/me/profile` upserts idempotently; `GET /v1/me/profile` returns it or a typed "not set", both `require_authenticated`-gated
- [ ] Two identities read/write their own profiles with no leakage; unauthenticated = 401
- [ ] Dual-seam discipline (facade, same-transaction, no cross-schema SQL)
- [ ] All failures answer the shared error envelope

## Read-list (in order)

1. `app/main.py` `/v1/me` route (L425-441) + `MeResponse` (L116-128) + `require_authenticated` - the auth gate to mirror; nowhere needs change, just read for the pattern (~400 tokens)
2. `modules/iam/facade.py` + `modules/iam/identity_facade.py` - where the new `save_patient_profile`/`get_patient_profile` facade functions go (identity facade is the MOD-001 seam) (~600 tokens)
3. `modules/iam/schema/models.py` + an iam alembic migration (`f28edd542d14...` pattern) - table + migration conventions, module isolation (no cross-schema FKs) (~800 tokens)
4. `tests/unit/test_iam_register_route.py` + `tests/unit/test_care_routes.py` - the `create_app(settings=...)` + stub-facade-in-`app.state.*` route-test pattern and JWT `issue_token` helper (~700 tokens)
5. `docs/architecture/internal-modules.md` MOD-001 §3 + coding-standards S2 module isolation + error-handling-observability envelope section (~500 tokens)

## Do NOT read

- care/consent/partner modules, frontend, AI pipeline, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run migration-check`
- Known pre-existing (unrelated): `test_app_shell` demo/OTP + `test_contract_check` fail under the local `DEFAULT_APP_ENVIRONMENT="dev"` override in `apps/backend/app/config.py`; frontend homepage parity fails on one Daltonganj string.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - profile PUT/GET contract, 401, identity isolation tests
- `npm run migration-check` - single-head gate + profile schema lands clean
- `npm run typecheck`

## Handoff notes

- `GET /v1/me` and its consumer stay stable - the profile gets its own read surface (this is a deliberate D-A decision).
- No cookie/CORS/middleware/deploy changes, so ADR-0007 is not implicated.
- The frontend half is ticket #488; this lands first and is the name/age source for #489.
