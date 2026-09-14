# ADR-0015: AI-assisted drafting posture for e-prescriptions

**Status:** accepted
**Date:** 2026-09-15
**Decides:** The regulatory posture of AI-drafted e-prescription content - what the AI may produce, how often, and what the doctor's fallback is - resolving `CFL-002` / `RISK-EVAL-003`.
**Traceability:** `FEAT-009`, `MOD-006`, `MOD-005`, `EXT-002`, `REQ-023`, `REQ-005`, `CFL-002`, `RISK-EVAL-003`, `NFR-001`.
**Evidence:** Phase 8 delivery (tickets #415-#425): `create_rx_draft` + the drafting-cap gate in the prescription machine, `request_rx_draft` facade seam (MOD-005), `care_rx_approvals`, ADR-0014.

## Context

`RISK-EVAL-003` names AI-drafted prescription content as the highest-stakes regulatory exposure in the product, and `CFL-002` left the pure-facilitator posture unvalidated (compliance stakeholder not elicited). The wrong posture - treating AI output as finalized clinical content, or routing drafts around the doctor - would break licensure authority and `REQ-023`. The product must ship a defensible, doctor-authoritative baseline now and leave room for a stricter regulatory gate later without a redesign.

## Decision

### 1. AI is a drafting assistant, never the author

AI output (`ai_draft` source) is a **draft snapshot** from the `EXT-002` model through the `MOD-005` `request_rx_draft` seam - an input to the doctor's review, never directly issuable content. Only the licensed doctor's explicit approval (ADR-0014 revision-freeze approval) turns a revision into an issued e-prescription.

### 2. Drafting cap: 3 AI attempts per case

Draft generation is capped at **3 attempts per case** (2 rejections), enforced by the prescription machine (`can_create_draft`). The cap limits AI draft _generation_ only; doctor authoring is never capped.

### 3. Manual-authoring fallback

The doctor can author the prescription directly (`manual` source) at any point - including after the drafting cap exhausts - so a doctor is never blocked from issuing by an AI constraint.

### 4. The approval gate is the compliance seam

All clinical-authority and regulatory tightening lands at the approval gate built in ADR-0014, not in the drafting pipeline. A stricter gate (e.g. human-in-the-loop review or practice-level sign-off) slots into the existing verification-declaration + revision-freeze action without moving the drafting path.

## Consequences

- Regulated acts remain `prescription.approved`, `prescription.rejected`, and `prescription.issued`; drafts and reviews are operational and stay out of the hash chain.
- `NFR-001` observe-and-warn budget metering is untouched (PS-10, ADR-0013).
- If the compliance stakeholder later mandates a stricter posture, the change is a gate-tightening change, and the cap + sources already give every attempt a traceable audit trail.
