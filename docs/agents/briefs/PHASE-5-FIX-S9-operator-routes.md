# Brief - 262 Phase-5 fix: operator login + invite HTTP routes (S9 · US-15)

**Ticket:** #262 · **Parent:** #243 · **Blocked by:** #261 (status filter landed after S8 TOTP) · **Refreshed:** 2026-09-01
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

There is NO operator login or operator invite HTTP route today - operator lifecycle is facade-seam + seed only (finding S9). Add the operator-facing routes so operators can log in (MFA-gated) and, per US-15, support operator invite. Wire them through `app/gateway/rbac.py` and the idempotency/TOTP seams (S8/#261).

Acceptance criteria (from #262):

- [ ] `POST /v1/auth/operator/session` (login) exists and is MFA-gated via the genuine TOTP check from #261.
- [ ] Operator invite/create route exists (guarded appropriately; uses `create_operator_account` which emits `operator.invited`).
- [ ] Routes are registered in `apps/backend/app/main.py`; error/422 mapping matches the repo envelope (see Handoff).

## Read-list (in order)

1. `apps/backend/modules/iam/adapters/routes.py` (48+) - the existing patient-only route surface: `register` (162), `verify` (185), `resend` (205), `session` (226), `refresh` (262). Mirror the session-route shape (request model, dependency wiring, 200/401 mapping) for operator sessions (~2K).
2. `apps/backend/modules/iam/facade.py` - `create_operator_account` (148-162, emits `operator.invited` EVENT_OPERATOR_INVITED bus/events.py:51), `record_mfa_verified` (176-184), `issue_operator_session` (192-198, MFA-gated) (~0.8K).
3. `apps/backend/app/gateway/rbac.py` - `require_operator` (54) and the `require_partner`/public-dependency pattern to reuse for the operator routes; see how `require_partner` is declared as a route dependency (~0.8K).
4. `apps/backend/app/main.py` - how the iam `auth` router is registered (near 249) and how error handlers + idempotency middleware attach, so the new operator routes inherit them (~0.8K).
5. `docs/spec/phase-5-partner-onboarding.md` US-15 - the operator login/invite requirements; and the T07 brief (`docs/agents/briefs/`) for the invite flow shape (~1K).

## Do NOT read

- notify/partner provider internals, partner routes (out of scope for the operator surface), `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`

## Done-verify (acceptance criteria -> commands)

- iam route + US-15 tests green (grep `operator` in tests; run iam route tests + full unit suite)
- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`
- `npm run typecheck`

## Handoff notes

- The operator surface is seam-only today: `IamFacade.create_operator_account`, `.record_mfa_verified`, `.issue_operator_session` exist; only a seed (`scripts/seed_demo.py:85-89` for `+919000000002`) uses them. The routes are the missing piece (S9).
- Reuse the existing patient `session` route pattern (request/response models, JWTs, error envelope). Login must call the #261 genuine TOTP gate - do not build login in a way that bypasses MFA.
- The repo's error envelope: 422 handlers like `INVALID_QUEUE_SORT` (routes.py:415-422) map domain exceptions to HTTP errors - follow that mapping convention for the operator routes (e.g. MFA failure -> a specific error code).
- Idempotency lives at the gateway (`app/gateway/idempotency.py`) keyed by path+key - sessions are naturally non-idempotent; confirm the route does NOT need the idempotency key (login emits a fresh session each call). Invite/create may want idempotency - wire it if US-15 requires exactly-once invite.
- Depends (native edge): #261 must land first so login's TOTP gate exists. The brief's read-list assumes #261 already shipped.
