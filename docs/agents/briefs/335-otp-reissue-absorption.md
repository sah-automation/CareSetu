# Brief - 335 OTP re-issue absorption + idempotency window (WI-4)

**Ticket:** #335 · **Parent:** #330 · **Refreshed:** 2026-09-06
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Absorb the duplicated OTP re-issue choreography into one shared primitive, and source the gateway idempotency window from the OTP lifetime constant.

The re-issue choreography (lock the identity row, evaluate the resend decision, invalidate pending challenges, issue a fresh challenge, send the code) is currently implemented in two places: the existing-number registration branch and the resend flow. This ticket extracts one shared OTP challenge re-issue primitive used by both paths, so cooldown and lockout semantics are defined once. Each flow maps the shared outcome to its own result type, preserving the distinct registration and resend responses - a patient logging in with an existing number and resending a code always behave identically against cooldowns and lockouts.

Separately, the gateway idempotency window hand-copies the OTP lifetime literal (both equal 300). This ticket sources the idempotency window from the OTP lifetime constant through an existing dependency seam, so the two values cannot drift apart. No new dependency direction results - the gateway already depends on the iam facade.

Acceptance criteria (from ticket):

- A single shared OTP challenge re-issue primitive exists and is used by both the existing-number registration branch and the resend flow.
- Each flow maps the shared outcome to its own result type, preserving the distinct registration and resend responses.
- The shared re-issue primitive reproduces identical cooldown/lockout decisions on both paths (integration/route test).
- The gateway idempotency window derives from the OTP lifetime constant by construction (the two values cannot drift); the hand-copied literal is removed.
- Existing iam integration and route suites pass unchanged.
- Full harness green: backend unit tests, integration tests, mypy strict typecheck, lint, migration single-head gate.

## Read-list (in order)

1. `apps/backend/modules/iam/otp_facade.py` 248-330 - `resend_otp` (current re-issue implementation #1) (~1.2K tokens)
2. `apps/backend/modules/iam/identity_facade.py` 116-211 - `register_patient`; the existing-number branch that re-issues (re-issue implementation #2) (~1.4K tokens)
3. `apps/backend/modules/iam/domain/shared.py` 56, 91, 110, 156 - the already-shared primitives (`_lock_identity_row`, `_invalidate_pending_challenges`, `_issue_challenge`, `_latest_cooldown_until`) the new primitive composes (~0.8K tokens)
4. `apps/backend/modules/iam/domain/resend.py` 25-60 - `ResendDecision` + `evaluate_resend` (pure decision) (~0.3K tokens)
5. `apps/backend/modules/iam/domain/otp.py` 18-19 - `OTP_TTL_SECONDS = 300`, `RESEND_COOLDOWN_SECONDS = 60` (the source const) (~0.1K tokens)
6. `apps/backend/app/gateway/idempotency.py` 30-40, 108 - `_DEFAULT_TTL_SECONDS = 300` (the hand-copied literal) + `run_idempotent`; confirm the iam dependency seam it sources through (~0.6K tokens)
7. Prior art: `tests/unit/test_iam_resend.py`, `tests/integration/test_iam_resend_lockout.py`, `tests/unit/test_idempotency_store.py`, register-via-existing-number route tests - behavior pins for both flows and the replay window (~1.2K tokens)

## Do NOT read

- The partner facade in any detail (separate chain).
- Session issuance / jwt / refresh internals; SMS adapter internals.
- Frontend, archives.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (1258 passed)
- `npm run typecheck`
- `npm run migration-check`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (all prior + new shared re-issue + window-equals-lifetime tests pass)
- `npm run test:integration`
- `npm run typecheck` (clean)
- `npm run lint`
- `npm run migration-check`

## Handoff notes

- No blockers - can start immediately, independent of the partner-facade chain. This is a frontier ticket alongside #331.
- The re-issue primitive composes the shared challenge primitives (`domain/shared.py`) - do not fork new lock/cooldown logic.
- Cooldown/lockout behavior after absorbing must be byte-identical on both paths; the registration-vs-resend response shapes stay distinct (each flow maps the shared outcome to its own result type).
- The idempotency window must be sourced from `OTP_TTL_SECONDS` through an existing dependency seam - no new iam->gateway or gateway->iam direction beyond what exists.
- A regression here is behavioral (both flows); the idempotency change is constructional (TTL source). Test both layers.
