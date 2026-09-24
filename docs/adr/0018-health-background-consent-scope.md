# ADR-0018: health_background as an independent consent scope, subsumed by full_record

**Status:** accepted
**Date:** 2026-09-24
**Decides:** US-35 of the parent spec (#529) - patient-authored health background becomes its own consent scope rather than hiding inside `full_record`, so patients can grant and revoke a doctor's access to it independently. Records the first-save acknowledgment that auto-grants the scope to a doctor the patient has a live relationship with, and that the scope is revocable in Settings like any other grant.
**Traceability:** `FEAT-002` (consent), `FEAT-020` (consent lifecycle), `MOD-004`, `NFR-SEC-006`, `NFR-D02`, `ADR-0004`. Implemented by #531 (scope plumbing) and #534 (first-save acknowledgment/auto-grant).

## Context

The `record scope` closed enum already gates five record areas (`consultations | prescriptions | lab_results | metrics | full_record`). The batch adds patient-authored health background - a PHI snapshot (blood group, conditions, allergies, medications, immunizations, family history) plus height/weight time series - that a doctor should see only under consent. If it were folded into `full_record`, a patient could not share only health background, nor revoke that access while keeping the rest of the record shared. The scope must be patient-legible (grant/revoke as a single understandable name), must ride the existing fail-closed `check_consent` gate and egress ledger unchanged, and existing grant rows must survive the addition.

## Decision

### D1 - New scope value, full_record subsumption preserved

`health_background` joins the closed enum exactly as `consultations | prescriptions | lab_results | metrics | health_background | full_record`. It is extended everywhere a record scope is a source of truth: the `RECORD_SCOPES` tuple, every `RecordScope` Literal (consent events and the audit consumer), and both database CHECK constraints on the consent lineage (`consent_consents.record_scope`) and egress ledger (`consent_egress_log.record_scope`). The migration is additive - the `IN (...)` lists are extended, never rewritten - so every existing row stays valid, and `full_record` continues to subsume `health_background` through the unchanged `_scope_subsumes` rule (`ADR-0004`). Grant, revoke, re-grant versioning, Redis cache keys, and egress disclosure all accept the new value in the same shape the existing scopes use.

### D2 - Grantable/revocable independently

`health_background` is granted, revoked, and versioned exactly like any other scope - no special casing in `grant_consent`/`revoke_consent`. A live `health_background` grant authorizes only health-background reads; a live `full_record` grant authorizes them too (subsumption); denial fail-closes to no data.

### D3 - First-save acknowledgment and auto-grant

The patient's first health-background save must carry an explicit acknowledgment that the snapshot is PHI surfaced to their verified doctors. That first acknowledged save records a `health_background` standing grant to every doctor the patient has a live care-loop relationship with at that moment (a live standing grant of any scope, or an open care case). The outcome is a normal consent grant - fully revocable later in Settings like any other scope - so the patient stays in control after the one-time explicit confirmation.

## Consequences

- A patient can share only health background, or revoke it, without touching the rest of the record - the US-35 property.
- `full_record` still covers the new scope, so existing full grants need no amendment and the doctor Patients entitlements (ADR-0019) are unaffected by which scope a patient granted.
- All existing rows survive the additive migration; the fail-closed gate, cache keys, and egress ledger keep their proven shape.
- The first acknowledged save is the consent-confirmation moment - after it, auto-grant and Settings revocation keep the grant fully patient-controlled.
