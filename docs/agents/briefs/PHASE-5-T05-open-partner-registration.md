# Brief - T05 Open partner registration (FEAT-014)

**Ticket:** #249 · **Parent:** #243 · **Refreshed:** 2026-08-31
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

A doctor/lab/chemist registers openly with phone + type + basic profile (practice location/geo mandatory, optional service area defaulting to Daltonganj); facade register method creates partner identity/profile, calls iam `create_credential_account` seam synchronously in the same transaction, emits `partner.registered`; pre-activation restricted login scope; duplicate phone resolves to existing identity. Unit + integration tests mirroring `test_iam_register_route.py` / `test_iam_registration.py`.

Acceptance criteria: see #249 body verbatim.

## Read-list (in order)

1. `apps/backend/modules/partner/facade.py` - current empty `PartnerFacade` (~0.2K)
2. `apps/backend/modules/partner/schema/models.py` - schema models from T01 (~0.3K)
3. `apps/backend/modules/partner/outbox.py` - `PARTNER_OUTBOX_TABLE` contract (~0.2K)
4. `apps/backend/modules/partner/domain/` - lifecycle state machine from T04 (~0.5K, will be populated by T04)
5. `apps/backend/modules/iam/facade.py` - how `create_credential_account` seam is called + `register_patient` pattern (~2.5K)
6. `apps/backend/modules/iam/identity_facade.py` - credential account creation internals (~2K)
7. `apps/backend/modules/iam/adapters/routes.py` - route registration pattern, unauthenticated endpoint layout (~4K)
8. `apps/backend/app/main.py` - how a module router + facade is mounted on `app.state` (~4K)
9. `apps/backend/app/gateway/rbac.py` - `require_partner` scope + restricted pre-activation scope (~1K)
10. `tests/unit/test_iam_register_route.py` - test pattern to mirror for partner registration (~2.5K)
11. `tests/integration/test_iam_registration.py` - integration test pattern to mirror (~4.5K)

## Do NOT read

- notify/audit internals, operator console internals, docs/archive/.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (874 passed, 1 warning - clean baseline)
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (new registration unit + integration tests green)
- `npm run typecheck`
- `npm run test:integration` (registration integration test)

## Handoff notes

- ADR-0010 (sync account): facade register method calls `create_credential_account` synchronously in the same DB transaction so the login account exists before the partner can log in. No outbox-based async delay for the IAM seam.
- The registration route is unauthenticated (like the iam auth surface) and accepts phone + partner_type (doctor | lab | chemist) + basic profile. Practice location/geo is mandatory; service area is optional and defaults to Daltonganj.
- Duplicate phone: if a partner identity already exists for the given phone, resolve to the existing identity and return it (no duplicate registration, no error).
- Pre-activation scope: the partner can log in via phone-OTP but gets a restricted scope (view status only; no patient-facing access while in `[Registered]`). The `require_partner` gate in `rbac.py` already exists - wire the pre-activation scope check.
- Outbox: emit `partner.registered` (from T04 event constants) into `partner_outbox` in the same transaction as the identity/profile creation.
- Module mounting: follow `app/main.py` pattern - partner facade on `app.state.partner_facade`, partner router mounted on the app.
- `register_handlers` in `modules/partner/adapters/__init__.py` already exists as a seam; no changes needed there for this ticket.
