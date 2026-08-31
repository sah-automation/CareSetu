# ADR-0010: Partner credential account created synchronously at registration

**Status:** accepted
**Date:** 2026-08-31
**Traceability:** `FEAT-014`, `MOD-002`, `MOD-001`.

## Context

The event registry subscribes `MOD-001` to `partner.activated` (to grant the partner role) but gives no explicit signal for when the partner's login credential account is created. A partner needs that account to exist before their first login (pre-activation, they log in with a restricted scope to track status, submit/re-submit credentials, and view rejection reasons). The codebase is strongly outbox/event-driven (`module isolation rule`), so the default assumption would be async account creation.

## Decision

**The `MOD-001` credential account is created synchronously at registration via the existing `MOD-002 → MOD-001` facade seam** (`create_credential_account`), in the same registration transaction boundary, so the account exists before the partner's first login.

## Consequences

- The partner profile, credential submission, and credential account are committed together at registration; the outbox carries the `partner.registered` audit event and the `partner.verification_started` event.
- No async dependency delays the partner's first login.
- `MOD-001` still subscribes to `partner.activated`/`partner.rejected` to flip the partner _role_ to active on gated activation (role grant/deny stays event-driven). The sync call only creates the restricted-account record; the role grant is the async, activation-gated step.
