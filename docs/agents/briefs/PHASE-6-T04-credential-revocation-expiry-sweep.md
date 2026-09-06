> **SUPERSEDED 2026-09-05** · #310 was split for session-size. This brief documents the union scope only. Implement via the sub-tickets:\n> - `PHASE-6-T04a-credential-revocation-scheduler.md` (#315) - revoke facade + first APScheduler job\n> - `PHASE-6-T04b-daily-credential-expiry-sweep.md` (#316) - daily expiry sweep\n

# Brief - PHASE-6-T04 Credential Revocation & Daily Expiry Sweep

**Ticket:** #310 · **Parent:** #306 · **Refreshed:** 2026-09-05 · **SUPERSEDED (see banner above)**
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Operators can revoke a partner's credential, instantly removing them from the directory and recording the reason. A daily sweep finds expired credentials and performs the official close-out: emits `credential.invalidated(reason=expired)` exactly once per credential, deindexes, audits. Revoked/expired partners recover by resubmitting through the existing verification flow (no new lifecycle state).

Acceptance criteria (from ticket):

- `invalidate_credential(partner, reason)` facade method emits `credential.invalidated` with `expired` or `revoked` reason and deindexes from `directory_index`
- Daily sweep job: queries `partner_credentials` where `expires_at` passed since last pass, emits `credential.invalidated(reason=expired)` for each, deindexes, audits
- Sweep integrated as first APScheduler periodic job in `worker/main.py` (mirrors daily backup cron pattern, ADR-0011)
- Lazy read-hide: search/verified indicator computed against recorded credential dates (expired partner hidden instantly)
- Revoked partner preserves identity/profile/history for re-verification (not re-registration)
- `credential.invalidated` fires exactly once per expired credential; lazy reads never emit events
- Tests: one event per expired credential (idempotent on replay), revocation deindexes, lazy reads never emit, re-verification recovery

## Read-list (in order)

1. `docs/adr/0011-credential-expiry-lazy-daily-sweep.md` - THE governing decision: lazy read-hide + daily sweep, no background scanner; sweep emits `credential.invalidated` (reason `expired`) exactly once per credential; revocation is immediate (not by sweep); detection latency ≤ one daily pass; sweep cadence is a changeable cost, not architecture. (~2.5K)
2. `CONTEXT.md` glossary - credential expiry vs credential revocation definitions; `[Active] → [Credential Revoked] → [Inactive]` read as a transition, not a new status. (~1K)
3. `internal-modules.md` §3.2 + §4.2 - expiry/revocation in MOD-002 scope; `credential.invalidated` already registered; `reason` gains `expired`/`revoked` alongside `reverification_failed`. Role denial in MOD-001 is already wired to `credential.invalidated` (Phase 5 T03 chain). (~1.5K)
4. `apps/backend/modules/partner/facade.py` - the existing `purge_expired_credentials` seam (grep it; line ~1548; docstring says it is the deterministic transactional trigger the Phase 6 periodic job invokes). Also the envelope-write-into-outbox-in-same-transaction pattern and `grace_lapse`/`operator_decision` for the re-verification-recovery behavior. (~2.5K)
5. `apps/backend/modules/partner/domain/events.py` - `CredentialInvalidatedPayload` builder + `reason` values; extend with `expired`/`revoked`. The event is a regulated act (in `REGULATED_ACT_TYPES`, audited via MOD-011). (~1K)
6. `apps/backend/modules/partner/outbox.py` - `PARTNER_OUTBOX_TABLE`; how outbox writes + consumed-event ledger work (idempotency on replay). (~0.5K)
7. `apps/backend/worker/main.py` - current worker composition root; no scheduler yet (APScheduler scaffold intentionally absent); this ticket introduces the first scheduled periodic job. Check `deploy/cron/` (`backup.sh`, `caresetu-backup.cron`, `README.md`) for the established daily-cron pattern and `npm run check:backup`/`backup-smoke` references. (~1.5K)

## Do NOT read

- Frontend code, consent/Redis module, IAM internals (only the already-subscribed `credential.invalidated` consumer role), notify module, prototype files, `docs/archive/`, ADRs beyond 0011/0012.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASSED 2026-09-05
- `npm run test:unit:backend` - PASSED 2026-09-05 (1205 passed)

## Done-verify (acceptance criteria → commands)

- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run test:integration` (needs local Postgres; skips if unreachable)

## Handoff notes

- Existing precedent: `tests/integration/test_partner_grace_window.py` `test_no_background_expiry_scan` explicitly reserves this Phase 6 expiry-sweep seam - it asserts no background scanner in Phase 5.
- Lazy reads (search/profile) NEVER emit `credential.invalidated`; only the sweep or the operator revocation call does. This keeps the events registry's at-least-once + idempotent-subscriber contract (ADR-0011).
- `credential.invalidated` with reason `revoked` also denies the MOD-001 partner role via the already-subscribed consumer chain - that behavior already exists; this ticket only adds the directory deindex + reason recording.
- The sweep must be idempotent on replay (one event per credential, not per pass) - likely keyed on a close-out marker; the `revoked_at`/`invalidation_reason` fields from T01 serve as that marker.
- No new partner lifecycle status is created; recovery = resubmit credentials through the Phase 5 verification-round flow.
