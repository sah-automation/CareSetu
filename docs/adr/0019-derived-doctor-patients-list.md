# ADR-0019: Doctor Patients list is derived - standing-grant lineage plus care cases, never a stored relationship

**Status:** accepted
**Date:** 2026-09-24
**Decides:** US-11/12/13 of the parent spec (#529) - how the doctor gets a Current/Past patient list without inventing a stored patient-relationship table. Current = live standing grant (any record scope) or an open care case; Past = closed care cases only with no live grant. The list is the care-loop anchor: a patient stays listed until the last grant is revoked.
**Traceability:** `FEAT-008`, `MOD-004`, `MOD-006`, `MOD-012` (Doctor Console seam), `ADR-0018`. Implemented by #539 (list) and #540 (detail).

## Context

A doctor needs a continuous-care view of the patients they may serve (US-11), with closed relationships readable as Past (US-12) and a patient remaining listed across visits so care loops reconnect effortlessly (US-13). Every entitlement ingredient already exists: the standing-grant lineage in `MOD-004` (which counterparty holds which live scopes) and the care cases in `MOD-006` (which doctor attended which visit, and whether the case is open or closed). A stored patient-relationship table would duplicate that lineage, need its own lifecycle (add/revoke/archive transitions), and create a second source of truth that could drift from the consent record - an unacceptable shape for a PHI access boundary.

## Decision

### D1 - Derived, never stored

The Patients list is computed on every read over two existing sources, with no new patient-relationship table and no new schema:

- **Current** = patients with a live standing grant to this doctor (any `record scope`, via the standing-grant lineage reverse lookup: rows whose counterparty is this doctor and status is granted) **or** an open/unclosed care case assigned to this doctor.
- **Past** = patients whose care cases with this doctor are all closed **and** who hold no live grant to this doctor.

A patient with neither a live grant nor a care case disappears from the list entirely; a patient with a live grant stays Current until the grant is revoked; after revocation they fall to Past only while a closed case exists, and drop off when the last closed case no longer binds them.

### D2 - Enrichment through existing facades

Row display (patient name, age, photo) and per-patient detail (contact, last case status, consent scopes) resolve through the doctor console seam's seamless reads over `MOD-004` (grant lineage + `check_consent`), `MOD-006` (care cases), and `MOD-001` (identity profile enrichment) - the same profile seam the review queue uses today. No module reads another module's tables; the derived list touches only facades.

### D3 - Every served row is access-logged

Each row actually returned to the doctor is recorded through the `MOD-003` access-history ledger (plus its `record.accessed` outbox envelope) in one transaction per row, using the caller-supplied scope marker `doctor_patients_list` (MOD-012 logs no scope of its own - the marker names the list surface, not a record entry, so revoking the underlying consent never rewinds the historical "viewed where" signal). Only rows in the returned page are logged: a read with no matches reveals nothing and logs nothing. Pagination (api-standards §4) bounds the ledger writes per request at the page size.

## Consequences

- One source of truth: the consent lineage is the access authority, and the list can never show someone the doctor may not read.
- Revocation is immediately effective: the moment the last grant is revoked and no open case remains, the patient leaves Current - no archival reconciliation pass.
- Care loops work naturally: patients returning to the same doctor stay listed and reconnect without a re-grant ceremony.
- The doctor console seam stays a read-side composition facade with no schema of its own (registered as `MOD-012`); the derivation logic is unit-testable against the two existing facades.
- **Registered exception to `coding-standards.md` §2 / ADR-0003:** a data module owns exactly one of the eleven private schemas; `MOD-012` owns none because it serves only derived reads over other modules' facades. This is a registered, explicit exception - the standard itself is unchanged, and any future schema-bearing console feature re-lands in the owning domain module or extends `MOD-012` to a real schema under a fresh ADR.
