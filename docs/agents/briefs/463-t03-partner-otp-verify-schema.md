# Brief - 463 F014-T03 Backend: partner OTP verify + phone-verified schema (POST /v1/auth/partner/verify)

**Ticket:** #463 · **Parent:** #460 · **Refreshed:** 2026-09-17
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

The partner completes login and the platform gains proof the caller owns the phone. `POST /v1/auth/partner/verify` consumes the one-time challenge and marks the partner's identity phone-verified (a new `iam_identities` column behind a migration), so a later session mint is bound to a phone the partner demonstrably controls. This is **silent** for the patient lifecycle: it grants no patient role and emits no `patient.verified` event - logging in as a partner never makes the phone a patient account. Wrong/expired/spent/locked outcomes behave exactly like the patient OTP surface.

Acceptance criteria (verbatim from ticket):

- [ ] A migration adds the phone-verified column to `iam_identities` (nullable, not backfilled - existing partners verify on next login, per the spec); the iam schema model is updated to match.
- [ ] `POST /v1/auth/partner/verify` with phone + valid code consumes the challenge and sets the phone-verified marker in the same transaction.
- [ ] The verify produces **no** patient role grant and **no** `patient.verified` outbox event (asserted in tests), and the identity lifecycle status is not flipped to `Active` as a side effect.
- [ ] Wrong code (attempt budget decremented), expired/spent ("request a new code"), lockout and suspended refusals match the patient surface; SMS-cost failures only feed the lockout counter (ADR-0004).
- [ ] The identity row is locked `FOR UPDATE` so a challenge is consumed exactly once.
- [ ] Route-seam tests cover: verified-and-marked, wrong/expired/spent/locked, and the no-role-grant / no-patient-event assertions.

**Blocked by:** #462 (partner OTP issue route) - shares the OTP machine vocabulary, result shapes and the same router file; sequence to avoid conflicts.

## Read-list (in order)

1. The iam auth router route + request-model pattern from `apps/backend/modules/iam/adapters/routes.py` (the `verify_otp` route, `run_idempotent`, error-handler registration) - the new `/partner/verify` slot. (~1.5K)
2. The OTP consumption path: `apps/backend/modules/iam/domain/verify.py` (`evaluate_attempt`, `failure_write_back`, `no_challenge_decision`, `suspended_decision`, `locked_decision`; outcome literals `verified|wrong_code|expired|spent|locked`) + `domain/shared.py` row-lock/invalidation helpers - the challenge evaluate + consume + lockout-accounting machine to reuse unchanged. (~2K)
3. `apps/backend/modules/iam/otp_facade.py` `verify_otp` (L~111-244) - the exact patient consumption path, read to replicate its evaluate/consume/lockout accounting while explicitly NOT copying its patient side effects (`_grant_patient_role`, `Active` transition, `patient.verified` emission). (~1.8K)
4. The iam schema + migration shape: `apps/backend/modules/iam/schema/models.py` (`iam_identities` table), the alembic chain under `apps/backend/alembic` (latest head is `fa5860abdb97` `v8_6__active_directory_index_backfill`; naming `v<major>_<minor>__snake_desc`), and the migration-check gate (`npm run migration-check` = single-head + no cross-schema FK). (~1K)
5. Route-seam test prior art: `tests/unit/test_iam_verify_route.py` + `tests/unit/test_iam_verify.py` (domain) - extend for the partner variant and the no-role-grant/no-event assertions. (~1.7K)

## Do NOT read

- Partner credential / verification internals, the patient-wizard frontend, operator MFA, `docs/archive/`, partner module source beyond the composition seams.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (2184 passed on 2026-09-17), `npm run lint`, `npm run typecheck`, `npm run migration-check` (single head `fa5860abdb97`) - all green this session.

## Done-verify (acceptance criteria → commands)

- `npm run migration-check` green with the new `iam_identities` column migration (single-head chain intact; no cross-schema FK).
- `npm run test:unit:backend` - new `/v1/auth/partner/verify` route tests + updated model tests.
- `npm run typecheck`, `npm run lint` green.

## Handoff notes

- The new column goes on `iam_identities` (nullable, no backfill); the model in `schema/models.py` must match the migration. The head is `fa5860abdb97` - the new migration's `down_revision` points at the current head revision hash; keep the chain linear.
- Consume a challenge exactly once via the `FOR UPDATE` identity row lock already used by `_lock_identity_row`; write the phone-verified marker in the same transaction as the consume.
- Do NOT flip identity lifecycle status to `Active`, do NOT call `_grant_patient_role`, do NOT build a `patient.verified` envelope. The event registry (§4.2 of internal-modules) has no `partner.verified` either - partner phone verification is silent by design.
- For the route-seam "no patient role / no patient event" assertions: the unit route tests stub the iam facade, so assert the stub shows no role-grant/event calls on the partner path (the real ledger proof is #470 integration). Keep the stub honest - the partner verify must not route through the patient verify side effects.
- Wrong/expired/spent/locked + current lockout counter semantics come from `domain/verify.py` + ADR-0004 (lockout counts SMS-cost failures only - refusals like locked/suspended are no-counter).
- ADR-0007 hard gate: this ticket touches auth routes but no cookie/session transport; still, do not alter `issue_partner_session` transport here - the mint tightening is #464.
