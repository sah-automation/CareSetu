# Brief - 332 Partner registration sub-facade (WI-2 p1a)

**Ticket:** #332 · **Parent:** #330 · **Refreshed:** 2026-09-06
**Reading surface:** ~10K tokens (budget 10K) - within budget

## Scope

Extract the partner registration lifecycle into its own sub-facade behind the thin coordinator (from #333), following the ADR-0006 IAM precedent. The coordinator delegates to the sub-facade while exposing an unchanged public interface.

The registration sub-facade owns `register`, `register_partner`, `resolve_partner`, `resolve_partner_id_by_identity`, `get_my_status` and their result models (`PartnerView`, `RegisterPartnerResult`, `PartnerMeView`). It takes the engine, the credential-validity deep module (from WI-1), and the iam facade (needed for the sync credential account) in its constructor. A developer changing registration behavior no longer reads credential-intake, operator-gate, or directory concerns.

Acceptance criteria (from ticket):

- Registration sub-facade exists owning the registration methods and their result models.
- `register` still creates the iam sync credential account via the iam facade (ADR-0010 path preserved).
- The coordinator delegates registration methods to the sub-facade and re-exports its result models (unchanged public interface; routes and cross-module callers unchanged).
- Sub-facade unit tests drive the sub-facade through a mocked engine (never importing private facade helpers or scripting exact SQL call order), mirroring the iam MFA facade direct-seam suite.
- Existing partner/iam integration and route suites pass unchanged.
- Full harness green: backend unit tests, integration tests, mypy strict typecheck, lint, migration single-head gate.

## Read-list (in order)

1. `docs/adr/0006-iam-facade-split.md` - the seam pattern to replicate (~1.5K tokens)
2. `docs/adr/0010-partner-account-sync-at-registration.md` - register-time iam sync contract (~0.3K tokens)
3. `apps/backend/modules/partner/facade.py` 911-985 - `register` method (race-retry + iam sync + events) (~1.5K tokens)
4. `apps/backend/modules/partner/facade.py` 987-1084 - `register_partner`, `resolve_partner`, `resolve_partner_id_by_identity`, `get_my_status` (~1.5K tokens)
5. `apps/backend/modules/partner/facade.py` 190-217, 354-371 - result models `PartnerView`, `RegisterPartnerResult`, `PartnerMeView` (~0.8K tokens)
6. `apps/backend/modules/partner/facade.py` - coordinator shape left by #333 (thin delegation; shared profile-load and race-retry helpers) (~0.5K tokens)
7. `apps/backend/modules/iam/identity_facade.py` 212-258 - `create_credential_account` seam called by register (~0.6K tokens)
8. Prior art: `tests/unit/test_partner_facade_register.py`, `tests/unit/test_mfa_facade.py` - register unit coverage + direct-seam pattern (~1.5K tokens)

## Do NOT read

- Credential-intake, operator-gate, and directory facade methods (separate sub-facade tickets).
- Close-out/eligibility internals beyond the shared deep-module interface (WI-1).
- IAM internals beyond `create_credential_account`; frontend; archives.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (1258 passed)
- `npm run typecheck`
- `npm run migration-check`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (all prior + new sub-facade direct-seam tests pass)
- `npm run test:integration`
- `npm run typecheck` (clean)
- `npm run lint`
- `npm run migration-check`

## Handoff notes

- Blocked by #333 (coordinator prefactor), which is blocked by #331. This is the earliest sub-facade ticket; Wi-3 (#336) blocks on it because the register path's iam usage is what makes the iam dependency genuinely required.
- Re-export the sub-facade's result models through the coordinator for backward compat (IAM precedent).
- The register-time iam sync (ADR-0010) must stay on this path unchanged; it is the reason the sub-facade keeps an iam reference.
- Direct-seam unit coverage drives the sub-facade through a mocked engine only - do not script exact SQL call order.
