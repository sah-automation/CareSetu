# Brief - T02 IAM sync partner credential account (ADR-0010)

**Ticket:** #245 · **Parent:** #243 · **Refreshed:** 2026-08-31
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

The MOD-001 (iam) change that lets a newly registered partner get a login account immediately (ADR-0010 "sync partner account at registration"). Add to MOD-001:

- A new typed facade method (e.g. `create_credential_account`) that creates the iam identity + a role grant, synchronous, in one transaction boundary, following the existing identity/role grant patterns (`register_patient`, `iam_role_grants` insert).
- The resulting account is usable for phone-OTP login but with a restricted scope until activation (role grant is the activation-gated step; no partner role yet).
- Unit tests proving the facade seam creates the account and the account can begin OTP login.

Acceptance criteria (from #245 body):

- [ ] A new iam facade method creates a partner credential account synchronously (matches ADR-0010 sync-boundary intent)
- [ ] The created identity is login-capable via phone-OTP but holds no `partner`/`patient` role grant yet
- [ ] Unit test covers the facade seam (route + facade split mirrors `test_iam_verify.py` / `test_iam_register_route.py`)
- [ ] Existing iam unit/integration suites stay green

## Read-list (in order)

1. `apps/backend/modules/iam/identity_facade.py` - THE reference for account creation: `register_patient` begin-or-resume pattern, `INSERT ... ON CONFLICT DO NOTHING` on the unique `phone_e164`, `write_outbox` for the registration event, `RegisterPatientResult` typed result (182 lines, ~2.4K)
2. `docs/adr/0010-partner-account-sync-at-registration.md` - the decision this ticket implements: sync identity+role-grant at registration, role grant stays the async activation-gated step (~0.3K)
3. `apps/backend/modules/iam/facade.py` - the `IamFacade` coordinator: how a sub-facade method is delegated and re-exported; add `create_credential_account` as a parallel delegation (~2.8K)
4. `apps/backend/modules/iam/otp_facade.py` (lines ~325-343 only) - `_grant_patient_role`: the idempotent role-grant insert pattern (`select existing -> insert` guarding a single `Active` grant) to mirror for the partner no-role / restricted-account case (~0.8K)
5. `apps/backend/modules/iam/schema/models.py` - `iam_identities` + `iam_role_grants` columns & role/status constraints the new method writes (~1.5K)
6. `apps/backend/modules/iam/domain/shared.py` - `_lock_identity_row`, `_identity_phone`, and the `OtpSender` port the sub-facade uses (~2K)
7. Unit-test pattern (facade/route split): `tests/unit/test_iam_register_route.py` (stub-facade + `app.state.iam_facade` pattern) and `tests/unit/test_iam_verify.py` (the decision-core style) (~2K total, skim)
8. `tests/integration/test_iam_registration.py` (head only) - the facade-through-typed-seam + EXT-001 stubbed pattern, `IamFacade` construction and `MutableClock` (~1K, skim)

## Do NOT read

- `modules/partner/*` internals beyond the fact that MOD-002 will call the new seam - partner-side wiring is a different ticket
- `session_facade.py` mint/session internals, `bus/*` ledgers/registry, `docs/archive/`
- The full `test_audit_consumer.py` / hash-chain machinery (unrelated to this ticket)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (874 passed, 1 StarletteDeprecationWarning on the current tree)
- `npm run typecheck` (mypy `--strict` + tsc)

## Done-verify (acceptance criteria -> commands)

- New iam facade unit test (the seam creates the account; the account is OTP-login-capable; no `partner`/`patient` role yet) - `npm run test:unit:backend`
- `npm run typecheck` (mypy strict - the new typed method/result model must type-check)
- `npm run test:integration` (needs local native PostgreSQL; iam registration suite green) - skips if PG unreachable

## Handoff notes

- **Blocked by** #244 (T01 schema foundation): `create_credential_account` writes `iam_identities` + `iam_role_grants`; the partner schema tables themselves do NOT need to exist for this ticket.
- The new account must be OTP-login-capable immediately - it creates an identity row (so the existing `verify_otp` / challenge machinery just works) but grants NO role. The restricted scope is the ABSENCE of a `partner`/`patient` role grant, not a new mechanics.
- The facade method should NOT emit `partner.registered` - the partner module emits that / the `activation` events in its own flow. Follow `register_patient`'s "write the audit/registration event in the same transaction" discipline only if the spec names one; otherwise keep account creation event-clean.
- The `iam_role_grants.role` check constraint is `('patient', 'partner', 'operator')` - there is no grant to write until activation; the method either creates the identity alone or writes a grant the consumer will later flip (T03 does the grant/deny). Match whatever ADR-0010 / the spec dictates for the initial row.
- Role grant/deny on `partner.activated`/`partner.rejected` is explicitly a DIFFERENT ticket (#248) - do not implement the consumer here.
- The `partner` role status values are `('Active','Suspended')` - the deny path in #248 flips `Active -> Suspended`, so keep the grant insert/update compatible.
- Keep the coordinator (`facade.py`) delegation + re-export style identical to the existing sub-facade pattern so the `IamFacade` public surface stays the only legal cross-module import target (ADR-0006).
