# Brief - PHASE-6-T04b Daily Credential Expiry Sweep

**Ticket:** #316 · **Parent:** #306 (split from #310) · **Refreshed:** 2026-09-05
**Reading surface:** ~4K tokens (budget 10K) - comfortably within budget

## Scope

A daily sweep job finds expired credentials and performs the official close-out: emits `credential.invalidated(reason=expired)` exactly once per expired credential, deindexes from the directory, and audits. Runs on the APScheduler seam + revoke deindex pattern scaffolded in #315. Lazy read-hide means expired partners are hidden from directory reads instantly even before the sweep runs - the sweep only performs the official event/audit close-out, never the correctness.

Acceptance criteria (from ticket):

- [ ] Expiry close-out method: queries `partner_credentials` where `expires_at` has passed since the last pass, marks close-out (`invalidation_reason='expired'`), deindexes from `partner_directory_index`, emits `credential.invalidated(reason='expired')` exactly once per credential with the close-out marker as the idempotency key (replay emits nothing)
- [ ] Sweep callback wired into the APScheduler job scaffolded in #315 (daily cadence mirroring the `deploy/cron/` backup convention, ADR-0011)
- [ ] Lazy read-hide: search and verified indicator always computed against recorded credential dates - an expired partner is hidden instantly, no job needed for correctness
- [ ] Lazy reads never emit events
- [ ] Audit: `credential.invalidated(reason='expired')` flows into the regulated-act hash chain (already a regulated act via MOD-011)
- [ ] Tests: sweep emits exactly one event per expired credential (idempotent on replay), lazy reads never emit events, expired partner hidden on reads before the sweep runs, sweep does not disturb the T04a revoke path

## Read-list (in order)

1. `docs/adr/0011-credential-expiry-lazy-daily-sweep.md` - THE governing decision: lazy read-hide + daily sweep, one event per credential, at-least-once + idempotent-subscriber, detection latency <= one daily pass. (~2.5K)
2. `apps/backend/modules/partner/facade.py` + `apps/backend/worker/main.py` - the revoke method + the scheduler seam #315 scaffolded (grep for the new names; do NOT read the whole files). (~1K)
3. `deploy/cron/` - the daily-cadence convention the sweep mirrors. (~0.5K)
4. Closing comment of #315 - the exact seam surface the sweep callback plugs into.

## Do NOT read

- Frontend code, consent/Redis module, IAM internals, notify module, prototype files, `docs/archive/`, ADRs beyond 0011/0012.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASSED 2026-09-05
- `npm run test:unit:backend` - PASSED 2026-09-05 (1211 passed)

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run test:integration` (needs local Postgres; skips if unreachable)

## Handoff notes

- Existing precedent: `tests/integration/test_partner_grace_window.py` `test_no_background_expiry_scan` asserts NO background scanner in Phase 5 - it reserves this Phase 6 seam. The expiry/revocation fields from T01 (#307) serve as the idempotency marker.
- Lazy reads (search/profile) NEVER emit `credential.invalidated`; only the sweep or the operator revocation call does.
- Replay safety: one event per credential, not per pass - key the pass on the close-out marker so a re-run emits nothing.
- Sweep must not disturb the revoke path or the permanent-rejection `purge_expired_credentials` cleanup.
- Blocked by #315 - starts once the revoke + scheduler scaffold lands.
