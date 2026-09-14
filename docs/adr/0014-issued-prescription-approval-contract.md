# ADR-0014: Issued e-prescription approval contract

**Status:** accepted
**Date:** 2026-09-15
**Decides:** What the approval action freezes into the issued e-prescription, what it requires, and how the doctor's edits are recorded - the `FEAT-009` issuance contract.
**Traceability:** `FEAT-009`, `FEAT-008`, `MOD-006`, `REQ-023`, `CFL-003`, `GAP-003`.
**Evidence:** Phase 8 delivery (tickets #417-#425): `CareFacade.approve_prescription` + `_check_approval_declaration`, the prescription state machine, `care_rx_approvals`, `prescription.approved` / `prescription.issued` payloads.

## Context

An e-prescription is a regulated artifact: `REQ-023` makes it a hard rule that none is ever issued without explicit doctor approval. Phase 8 has to fix which artifact approval actually freezes. A single draft flows through the case:

- The AI drafting assistant's **draft snapshot** (`ai_draft`) is immutable and stored once per attempt.
- The doctor then edits on a **working revision**; the draft and the revision can diverge (`FEAT-009` scenario 2 - doctor edits before approval).

If approval froze the snapshot, the doctor's edits would silently drop and the issued prescription would contradict the reviewed record. The other ambiguity is process control: nothing forces the doctor to double-check the finalized content before signing, and nothing records that edits happened for the audit trail.

## Decision

### 1. Revision-freeze approval

Approval freezes **exactly the doctor's saved working revision**, never the raw draft snapshot. The draft snapshot is a drafting-assistant input artifact and is never directly issuable (CONTEXT.md glossary, `draft snapshot` / `revision-freeze approval`).

### 2. Mandatory verification declaration

Approval is refused unless the doctor asserts `verification_declaration = true` - the double-check declaration that the finalized revision is clinically correct and personally reviewed (CONTEXT.md glossary, `verification declaration`). The gate is enforced by the prescription machine transition and re-checked in the facade before the state change commits; a `false`/missing declaration blocks the transition.

### 3. edited_yn records edits

On approval, `edited_yn` is derived by comparing the issued revision against the immutable draft snapshot. The boolean (never the diff) travels on `prescription.approved`; the clinical content stays in the `care` schema (no-PHI envelope).

### 4. Issued e-prescription is immutable and attributed

Issuance stamps `issued_at` and `attributed_doctor`; the issued artifact is immutable with no supersede or void path (CONTEXT.md glossary, `e-prescription`). `prescription.approved` and `prescription.issued` are regulated acts and enter the audit hash chain.

### 5. Doctor-initiated handshake is the delivered baseline

`CFL-003` / `GAP-003` (who triggers the off-platform consult to on-platform prescription handshake) is resolved: the doctor initiates, delivered via `CareFacade.mark_consult_complete`. Patient-initiated handshake remains out of scope.

## Consequences

- A rejecting draft never auto-closes the case; closing is the doctor's deliberate `close-without-prescription` action (`case.closed`).
- The approval seam is the single substitution point if a stricter gate ever lands: tighten this action, not the drafting pipeline.
- The drafting cap and AI posture are decided separately in ADR-0015.
