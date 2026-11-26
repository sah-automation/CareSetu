# Brief - T04 Partner lifecycle state machine + event catalog

**Ticket:** #247 · **Parent:** #243 · **Refreshed:** 2026-08-31
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

The lifecycle engine for the two-step verification gate (ADR-0008): partner event constants + payload builders in `bus/events.py` (`partner.registered`, `partner.verification_started` per-round, `partner.activated`, `partner.rejected` with reason, `partner.credential_reviewed`, `credential.invalidated`); a pure lifecycle state machine in `modules/partner/domain/` (Registered -> Under Verification -> Active | Rejected, no-auto-approve guarantee, Step-1 auto-fail path, verification rounds, 7-day grace window); `modules/partner/facade.py` (currently empty) + outbox wiring; register events in event catalog / internal-modules, and extend `_GATED_DOMAINS` in `scripts/check_event_names.py` to include `partner`.

Acceptance criteria: see #247 body verbatim.

## Read-list (in order)

1. `apps/backend/bus/events.py` - canonical event constants + `REGULATED_ACT_TYPES`; partner strings already there as literals (~1K)
2. `apps/backend/modules/iam/domain/events.py` - envelope/payload-builder pattern: `PatientRegisteredPayload`, `patient_registered_envelope` - THE reference for partner event builders (~1.5K)
3. `apps/backend/modules/consent/domain/state_machine.py` - consent state machine = THE prior-art for the partner lifecycle state machine (~1K)
4. `tests/unit/test_consent_state_machine.py` - state-machine test pattern to mirror (~1K)
5. `apps/backend/modules/partner/facade.py` - current empty `PartnerFacade` (~0.2K)
6. `apps/backend/modules/partner/outbox.py` - `PARTNER_OUTBOX_TABLE` contract (~0.2K)
7. `apps/backend/modules/partner/schema/models.py` - schema models from T01 (~0.3K)
8. `apps/backend/scripts/check_event_names.py` - `_GATED_DOMAINS` at top, add `partner` (~1.5K)
9. `docs/architecture/internal-modules.md` lines 596-644 - event registry §4.2, add partner events (~0.5K)
10. `tests/unit/test_bus_event_catalog.py` - event-catalog unit test to extend (~0.3K)
11. `tests/unit/test_regulated_acts.py` - regulated-acts test to verify partner events covered (~1K)

## Do NOT read

- notify/audit/iam internals beyond the files named, operator console internals, unrelated modules, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (874 passed, 1 warning - clean baseline)
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (new state-machine unit tests + existing tests green)
- `npm run typecheck`
- Event catalog / regulated-acts tests pass (subset of unit suite)

## Handoff notes

- Promote the four literal partner strings in `REGULATED_ACT_TYPES` (`"partner.registered"`, `"partner.activated"`, `"partner.rejected"`, `"credential.invalidated"`) to named constants and reference them. Add `partner.verification_started`, `partner.credential_reviewed` as new constants.
- State machine mirrors `modules/consent/domain/state_machine.py`: valid transitions from any start state, operator approve -> `[Active]`, operator reject -> `[Rejected]` with reason, Step-1 auto-fail -> `[Rejected]` (never queued). No path reaches `[Active]` without explicit operator decision (no auto-approve).
- Re-verification rounds: each new verification opens a new round with `verification_started` carrying round/version in payload.
- 7-day grace window: expired credentials trigger `credential.invalidated` after 7 days.
- `partner.credential_reviewed` carries actor + partner + timestamp; emitted by the operator review handler (separate ticket) but the constant and payload builder are defined here.
- Register the new partner events in `docs/architecture/internal-modules.md` §4.2 table (rows for `partner.registered`, `partner.verification_started`, `partner.activated`, `partner.rejected`, `partner.credential_reviewed`, `credential.invalidated`) and ensure `test_bus_event_catalog.py` covers them.
- `_GATED_DOMAINS` in `scripts/check_event_names.py` gets `"partner"` added to the tuple.
