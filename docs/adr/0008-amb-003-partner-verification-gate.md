# ADR-0008: AMB-003 resolution - the two-step partner verification gate

**Status:** accepted
**Date:** 2026-08-31
**Decides:** `AMB-003` (PRD §7.1) - the partner verification mechanism for gated activation.
**Traceability:** `FEAT-014`, `FEAT-015`, `MOD-002`, `MOD-001`, `REQ-028`, `NFR-001`, `KPI-004`.

## Context

`AMB-003` was left open at baseline: "verification mechanism (fully automated vs. automated + manual review) is undecided - it directly affects operator headcount under `NFR-001`." Baseline suggested automated checks with manual review for flagged cases. `FEAT-015` requires the operator console to gate activation, and `KPI-004` targets a ≤ 48 h median activation cycle. Phase 5 has no machine-verifiable external credential sources - only uploaded credential artifacts - so no automated check can prove a credential's validity.

## Decision

**Two-step verification, where the automated step is a pre-filter, never an approval.**

1. **Step 1 (automated, synchronous on submission):** Format validation (credential type is a known enum value, required fields present, artifacts uploaded, no duplicate registration). A failure returns `[Rejected]` immediately with a specific failure reason and never enters the operator queue. Passing is **not** approval - it only advances to Step 2.
2. **Step 2 (manual, the activation gate):** Every submission that passes Step 1 enters the operator queue for final human review. There is **no auto-approve path** - a partner reaches `[Active]` only by explicit operator approval. No partner is activated without a human having looked at the submission.

This deliberately trades the low headcount of full automation for the guarantee that a bad partner can never slip through automated checks that cannot actually verify credentials (no machine-verifiable source in Phase 5). The operator pool is a trusted closed group (bootstrap + invites), and `KPI-004` is met through queue prioritization by registration age, not through automation.

## Consequences

- No partner reaches `[Active]` without operator approval; the state machine is `[Registered] → [Under Verification] → [Active] | [Rejected]`.
- Step 1 auto-fail is a cheap pre-filter that keeps obvious/bad submissions out of the operator queue, bounding headcount.
- The automated check is deliberately limited to what is verifiable in Phase 5 (format + duplicate). Deeper registry checks are a future decision, not a Phase 5 capability.
- Operator decisions are individually attributed and audited; the operator console forbids bulk approve/reject so every decision maps to an actor.
- `KPI-004` (≤ 48 h median activation) is met by age-prioritized queue ordering, not by automation.
