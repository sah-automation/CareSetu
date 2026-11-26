# Brief - T10 Active-partner grace-window re-verification + deactivation

**Ticket:** #254 · **Parent:** #243 · **Refreshed:** 2026-08-31
**Reading surface:** ~6.5K tokens (budget 10K) - within budget

## Scope

The grace-window re-verification for active partners (renewal). An `[Active]` partner who re-submits updated credentials keeps practicing through a 7-day grace window with no disruption. If the window lapses without a decision, they auto-drop to `[Under Verification]`. If reverification fails, they are `[Rejected]` with a specific reason and `credential.invalidated` fires - which deindexes them from any directory and revokes the iam role (through T03).

From the user's perspective: an active partner can renew credentials without losing their ability to practice mid-flight; a renewal that fails cleanly removes them from future routing.

Implementation:

- The 7-day grace-window logic in the lifecycle state machine (active partner re-submits -> stays `[Active]` for 7 days; success -> no disruption; lapse -> auto-drop `[Under Verification]`; failure -> `[Rejected]`).
- Emit `credential.invalidated` on reverification failure; this drives role denial (T03) and directory deindex.
- Note: background expiry-scanning is explicitly out of scope (Phase 6) - this is the event-driven reverify-grace path only.

Acceptance criteria (verbatim from #254):

- [ ] An active partner re-submitting stays `[Active]` within the 7-day grace window
- [ ] Window lapses without a decision -> auto-drop to `[Under Verification]`
- [ ] Reverification failure -> `[Rejected]` with specific reason and `credential.invalidated` emitted
- [ ] `credential.invalidated` drives iam role denial (T03 chain observable through the iam facade)
- [ ] No background expiry-scan in scope (documented as Phase 6)
- [ ] Unit + integration tests cover the grace-window transitions

## Read-list (in order)

1. `modules/partner/domain/state_machine.py` - T04-built state machine; the grace-window transitions (active re-submit stays `[Active]`, lapse -> `[Under Verification]`, failure -> `[Rejected]` + `credential.invalidated`) are already sketched here, extend into the reverify path (~2K)
2. `modules/partner/schema/models.py` - `partner_credentials` (expiry), `partner_verifications` (round + decision); the grace-window state it records (~0.6K)
3. `modules/partner/facade.py` - expose the renewal re-submit + lapse-decision operations through the typed seam (~0.7K)
4. `modules/iam/facade.py` - `credential.invalidated` consumer/role-revocation seam (T03 #248) - the audit-observable effect this ticket's `credential.invalidated` must drive (only the facade contract, not iam internals) (~0.8K)
5. `apps/backend/bus/events.py` - the `credential.invalidated` constant + `REGULATED_ACT_TYPES` membership (it is already whitelisted) (~0.4K)
6. `tests/unit/test_consent_state_machine.py` + a T08-style verification test - the transition test pattern to mirror for the grace window (~1K)

## Do NOT read

- notify internals, audit append internals, iam SMS/OTP internals, `docs/archive/`. Background expiry-scanning is out (Phase 6) - this is purely the event-driven reverify-grace path.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (874 passed, 1 warning - clean baseline)
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- New grace-window unit + integration tests green (subset of unit suite)
- `npm run test:unit:backend`
- `npm run typecheck`
- `npm run test:integration`
- `npm run migration-check`

## Handoff notes

- Blocked by #252 (T08 - operator verification queue + approve/reject: the reverify decision and the `partner.activated` base). T04 (#247) already built the 7-day grace window into the state machine - this ticket wires the reverify-grace flow around it, not a from-scratch grace window.
- `credential.invalidated` is already a literal in `REGULATED_ACT_TYPES` (T04 promotes it to a constant) - emitting it on reverification failure is the trigger; do NOT also emit it for the mere lapse-to-`[Under Verification]` (that is not a deactivation).
- The `credential.invalidated` effect (role denial + directory deindex) is consumed through the T03 iam chain (#248) - this ticket only emits the event; it does not reach into iam. Verify the chain end-to-end via the iam facade contract, not by touching iam's schema.
- Timeline is event-driven only: the lapse auto-drop is triggered by the reverify flow's deadline, not by a scheduled scanner (that is Phase 6 - document it as such in a note).
- Prior art: ADR-0008 two-step gate (operator-only activation), T04 state machine grace-window transitions.
