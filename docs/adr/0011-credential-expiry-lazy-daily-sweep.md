# ADR-0011: Credential-expiry detection - lazy read-hide plus a daily sweep, no background scanner

**Status:** accepted
**Date:** 2026-09-05
**Traceability:** `FEAT-005`, `MOD-002`, `credential.invalidated`, `REQ-028`, `NFR-001`.

## Context

`FEAT-005` requires that on credential expiry/revocation the partner is deindexed (removed from directory search) and the verified indicator removed. A naive reading suggests a background scanner that polls `partner_credentials` for expired rows. The codebase holds an explicit "deliberately no scanner" doctrine (Phase 5: deactivation is event-driven, never polled), and `NFR-001` forbids machinery whose only job is watching. There is no machine-verifiable renewal signal, but expiry is deterministic - the credential's recorded date is known in advance.

## Decision

**Expiry is handled by two cooperating, non-scanner mechanisms:**

1. **Lazy on the read path.** Directory search and the verified indicator are always computed against the credential's recorded date. An expired credential is never displayed, even minutes after the date passes - no background job needed for correctness.
2. **A daily sweep** (mirroring the established daily cron pattern used for backups) that finds credentials which expired since the last pass and records the official close-out: emits `credential.invalidated` (reason `expired`), marks the deindex, and audits it, so the event-triggered chain (role denial, partner notification when notifications exist) still fires exactly once.

A credential whose date simply passed is the deferred/expiry path; a credential taken away by authority or operator decision is `credential.revoked` and follows the same close-out immediately (ADR-0011 covers the timing only; the partner lifecycle consequence is the ADR-0012 renewal path).

## Consequences

- The patient-facing side is honest at any instant a search runs; the worst-case display lag is bounded by the daily sweep for the _recorded_ close-out, not for what a patient sees.
- No background scanner exists; the sweep reuses the cron + scheduler pattern from the daily backup job and its cost is a single indexed query per day.
- `credential.invalidated` fires exactly once per expired credential (lazy reads never emit it - they only suppress display), preserving the events registry's at-least-once + idempotent-subscriber contract.
- Detection latency for official bookkeeping is ≤ one daily pass; if that bound is ever unacceptable, the sweep cadence changes, not the architecture.
