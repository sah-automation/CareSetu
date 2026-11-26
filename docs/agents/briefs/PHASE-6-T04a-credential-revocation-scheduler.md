# Brief - PHASE-6-T04a Credential Revocation & Worker Scheduler Scaffold

**Ticket:** #315 · **Parent:** #306 (split from #310) · **Refreshed:** 2026-09-05
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Operators can revoke a partner's credential immediately, removing them from the directory and recording the reason. This ticket also introduces the first APScheduler periodic-job scaffold in the worker (the mechanism the daily expiry sweep in T04b runs on). The daily sweep logic itself is deliberately not here - only the scheduler seam plus a stub sweep hook that #316 fills.

Acceptance criteria (from ticket):

- [ ] `invalidate_credential(partner, reason)` facade method: sets the close-out marker (`revoked_at`/`invalidation_reason='revoked'`), deindexes from `partner_directory_index`, emits `credential.invalidated(reason='revoked')` in the same transaction (outbox pattern, mirrors `purge_expired_credentials`)
- [ ] Revoked partner preserves identity, profile, and history for re-verification (not re-registration) - no new lifecycle state
- [ ] APScheduler added to `apps/backend/pyproject.toml` dependencies
- [ ] First scheduled periodic job scaffolded in `apps/backend/worker/main.py` (configurable cadence; sweep callback is a stub hook that the T04b sweep ticket fills)
- [ ] Lazy read-hide: revoked partner hidden from directory reads instantly, computed against recorded dates (ADR-0011)
- [ ] Tests: revocation deindexes + emits exactly one event in the same transaction, re-verification recovery possible after revocation

## Read-list (in order)

1. `docs/adr/0011-credential-expiry-lazy-daily-sweep.md` - THE governing decision: lazy read-hide + daily sweep, no background scanner; revocation is immediate (not by sweep); sweep cadence is a changeable cost, not architecture. (~2.5K)
2. `CONTEXT.md` glossary Phase 6 - credential expiry vs credential revocation; `[Active] -> [Credential Revoked] -> [Inactive]` reads as a transition, not a new status. (~1K)
3. `internal-modules.md` §3.2 - expiry/revocation in MOD-002 scope; `credential.invalidated` already registered; role denial in MOD-001 already wired to it (Phase 5 T03 chain). (~1K)
4. `apps/backend/modules/partner/facade.py` - the existing `purge_expired_credentials` seam (grep it; ~line 1548; transaction + delete + artifact removal + outbox `credential.invalidated` write pattern) - the direct template for the revoke method. Also `operator_decision`/`grace_lapse` for the re-verification-recovery read path. Grep; do NOT read the whole file. (~2K)
5. `apps/backend/modules/partner/domain/events.py` - `CredentialInvalidatedPayload` builder; `reason` is free-text str, no payload change needed; event already a regulated act (MOD-011). (~0.5K)
6. `apps/backend/worker/main.py` - composition root, outbox poll loop, no scheduler yet; `deploy/cron/` for the daily-cadence precedent. (~1.5K)

## Do NOT read

- Frontend code, consent/Redis module, IAM internals (only the already-subscribed `credential.invalidated` consumer role), notify module, prototype files, `docs/archive/`, ADRs beyond 0011/0012.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASSED 2026-09-05
- `npm run test:unit:backend` - PASSED 2026-09-05 (1211 passed)

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run test:integration` (needs local Postgres; skips if unreachable)

## Handoff notes

- `purge_expired_credentials` handles the _permanent-rejection 30-day cleanup_ path, NOT expiry/revocation - it is the template, not the method to extend.
- APScheduler is NOT a dependency yet - it must be added to `pyproject.toml`.
- `credential.invalidated` with reason `revoked` denies the MOD-001 partner role via the already-subscribed consumer chain - that already works; this ticket only adds the directory deindex + reason recording.
- No new partner lifecycle status: recovery = resubmit credentials through the Phase 5 verification-round flow.
- The deindex write into `partner_directory_index` is greenfield - no facade method touches the table today beyond the #307 backfill.
- Blocked by #307 (credential close-out fields + `directory_index`) - starts once #307 closes.
