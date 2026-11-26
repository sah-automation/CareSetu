# Brief - T09 Rejection recovery: re-submit + one-time appeal + throttle

**Ticket:** #253 · **Parent:** #243 · **Refreshed:** 2026-08-31
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

The rejected-partner recovery paths: a partner who is `[Rejected]` learns the specific failure reason, and can either re-submit corrected credentials (a fresh verification round) or file a one-time appeal that re-enters the operator queue. Both are rate-limited (max 3 re-submissions before a cooldown) so the queue cannot be spammed.

From the user's perspective: a rejected partner is not dead-ended - they see why they failed and have a bounded path to try again or contest the decision once.

Implementation:

- Partner-facing route to view their rejection reason.
- Re-submit corrected credentials -> starts a new verification round (a fresh `partner.verification_started` with round > 1) through Step 1 and back into the operator queue.
- One-time appeal -> re-enters the operator queue once (flag consumed on use).
- Throttle: enforce the max-3 re-submissions then a cooldown (newly rejected partners throttled to protect the queue).
- Unit/integration tests for the round increment, the one-time appeal, and the throttle boundary.

Acceptance criteria (verbatim from #253):

- [ ] A `[Rejected]` partner can view the specific rejection reason
- [ ] Re-submitting corrected credentials starts a new round (round > 1) and re-enters the operator queue with a fresh `partner.verification_started`
- [ ] A one-time appeal re-enters the queue and can only be used once
- [ ] The 3-re-submission throttle then cooldown is enforced
- [ ] Unit + integration tests mirror the state-machine test style

## Read-list (in order)

1. `modules/partner/domain/state_machine.py` - the T04-built lifecycle engine (round counting, `[Rejected]` terminal, the transitions recovery reuses); read the re-verification-round + reject-reason paths (~2K)
2. `modules/partner/schema/models.py` - `partner_verifications` (round counter), `partner_credentials`, and the appeal/throttle columns to add (migration) (~0.5K)
3. `modules/partner/facade.py` - the typed facade seam to expose the view-reason / re-submit / appeal operations (~0.7K)
4. `modules/partner/adapters/routes.py` - T06/T08-built partner routes; add the view-reason + re-submit + appeal routes here following the existing pattern (~1.5K)
5. `apps/backend/bus/events.py` - the T04-promoted partner constants + `REGULATED_ACT_TYPES`; re-submission reuses `partner.verification_started`, appeal re-entries the queue (~0.8K)
6. `tests/unit/test_consent_state_machine.py` + a T08-style verification test - the state-machine test pattern to mirror for round-increment / one-time-appeal / throttle (~1K)
7. `apps/backend/scripts/check_event_names.py` - `_GATED_DOMAINS` already has `partner` (from T04); no change, just confirm (~0.2K)

## Do NOT read

- iam/notify/audit internals, the operator console frontend, unrelated modules, `docs/archive/`. The throttle is a domain/business rule (state-machine guarded), not an iam/Redis rate limiter.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (874 passed, 1 warning - clean baseline)
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- New re-submit/appeal/throttle unit + integration tests green (subset of unit suite)
- `npm run test:unit:backend`
- `npm run typecheck`
- `npm run test:integration`
- `npm run migration-check`

## Handoff notes

- Blocked by #251 (T06 - credential submission + Step-1 pre-filter: re-submission reuses the same pre-filter) and #252 (T08 - operator verification queue + approve/reject: re-entering the queue and the first rejection decision). Do not begin until both land - the partner routes/queue they build are the base this ticket edits.
- T04 (#247) already built the round-counting state machine and promoted the partner event constants in `bus/events.py`; `_GATED_DOMAINS` has `partner`. Re-submission is "new verification round, round > 1, fresh `partner.verification_started`", NOT a brand-new `[Registered]` lifecycle.
- The rejection reason is the `[Rejected]` transition reason stored by T08; the view-reason route reads it back for the partner.
- One-time appeal: a flag on the verification record consumed on first use - a second appeal attempt is rejected/ignored. The appeal re-enters the operator queue (Step 2) but does NOT bump the re-submission counter.
- Throttle is a business rule in the state machine / facade guard (max 3 re-submission rounds then cooldown), protecting the operator queue (`NFR-001` headcount, ADR-0008). Never enforced via iam/Redis lockout - that is not this module's seam.
- Every accepted re-submission / appeal publishes the same bus events as a first submission (`partner.verification_started`) so downstream consumers (notify T12, audit T13) behave uniformly.
- Prior art: ADR-0008 two-step gate (reject reason + operator-only activation), `modules/consent/domain/state_machine.py` transition patterns.
