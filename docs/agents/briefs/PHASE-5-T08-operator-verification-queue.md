# Brief - T08 Operator verification queue + approve/reject (FEAT-015)

**Ticket:** #252 · **Parent:** #243 · **Refreshed:** 2026-08-31
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

The operator verification console = the manual activation gate (Step 2, ADR-0008). Implement:

- Operator-scoped (`require_operator`) routes: queue list, per-partner detail (profile + all submitted credentials + verification history), approve/reject with required reason on reject
- Queue sortable/filterable by registration age (default), partner type, status
- Approve -> partner `[Active]` emits `partner.activated` -> iam role grant (#248 chain)
- Reject (required reason) -> `[Rejected]` emits `partner.rejected` -> role denied
- No bulk actions, individually attributed
- Opening credentials emits `partner.credential_reviewed` (audit consumption is a later ticket, but the event is emitted here)
- Tests mirroring `test_regulated_acts.py` / `test_audit_chain.py`

Acceptance criteria: see #252 body verbatim.

## Read-list (in order)

1. `apps/backend/modules/iam/facade.py` - facade pattern: coordinator + sub-facades, typed methods, role grant observable surface from #248 (~2.1K)
2. `apps/backend/modules/partner/schema/models.py` - current schema scaffold, confirms `partner_verifications` table comes from #244 and state machine columns from #247 (~0.2K)
3. `apps/backend/modules/partner/adapters/__init__.py` - current empty `register_handlers()` pattern, the reference for mounting partner routes (~0.1K)
4. `apps/backend/modules/partner/domain/exceptions.py` - base `PartnerError`, extend for verification queue domain errors (~0.1K)
5. `apps/backend/bus/events.py` - `partner.activated`, `partner.rejected` string constants already in `REGULATED_ACT_TYPES`; `partner.credential_reviewed` to add (~0.9K)
6. `apps/backend/modules/iam/adapters/routes.py` - route pattern: thin adapter calling facade, request/response models, error envelope registration (~4K)
7. `apps/backend/modules/iam/schema/models.py` - `iam_role_grants` table for asserting role grant chain on approve (~1.1K)

## Do NOT read

- `apps/backend/modules/iam/session_facade.py` (session minting, not in scope)
- `apps/backend/modules/health/` or `modules/consent/` (different domains)
- `apps/backend/scripts/seed_demo.py` (patient seed, not relevant)
- `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (verification queue tests green)
- `npm run typecheck`
- `npm run migration-check`

## Handoff notes

- The `partner_verifications` table (from #244) holds queue rows: one row per partner registration round, with status, rounds, and decision columns. The state machine transitions come from #247.
- Approve flow: update `partner_verifications` status to `Approved`, update `partner_identities` status to `Active`, emit `partner.activated` via outbox, then call through the iam facade to grant the `partner` role (#248 chain).
- Reject flow: update status to `Rejected` (requires `reason` field), emit `partner.rejected` via outbox, deny role grant.
- `partner.credential_reviewed` event is emitted when the operator opens a credential detail view (not on approve/reject) - audit consumption is a later ticket.
- The queue list query sorts by `created_at` descending by default (registration age), filterable by `partner_type` and `status` query params.
- Blocking chain: #248 (role grant chain) -> #250 (operator login, so operators can reach the routes) -> #251 (partner credential submission) -> this ticket. #248 is the critical path for the approve/reject -> role grant chain test.
