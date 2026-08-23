# Brief - T08 Operator console information architecture

**Ticket:** #186 · **Parent:** #178 Wayfinder map: Top-level UI Blueprint · **Refreshed:** 2026-08-21
**Reading surface:** ~4K tokens (budget 10K) - within budget

## Scope

Decision question (verbatim): Top-level areas of the operator console: partner verification queue and activation gating, dispute moderation, audit log viewer, access-history queries; what the operator home screen prioritizes.

Resolution must produce: the operator nav map with key screens at wireframe-description level (verification queue with credential review + activate/reject-with-reason, moderation, audit viewer, access history), and the operator home priority list. Uses shell conventions from #182 as fixed input.

## Read-list (in order)

1. #182 closing comment - shell conventions (~0.5K)
2. `docs/prd/project-prd.md` §4.7.2 `FEAT-015` Operator Console - Verification & Moderation (~1.5K)
3. `docs/prd/project-prd.md` §4.10.1 `FEAT-020` Audit Trail & Consent Lifecycle - what the audit viewer shows (~1.5K)
4. `docs/prd/project-prd.md` §4.1.3 `FEAT-003` Patient Record Access & Audit View - access-history query surface (~1K)

## Do NOT read

- Patient/doctor/partner epics beyond handoff points, backend modules, roadmap, archive docs.

## Baseline verify (must pass before the first edit)

- None - read-only decision session; do not edit code.

## Done-verify (acceptance criteria → commands)

- Resolution comment on #186 with the IA; ticket closed
- Map #178 Decisions-so-far gains one line linking #186

## Handoff notes

- Operator is an internal, desktop-leaning console - density is acceptable here unlike patient surfaces; still respect the page budget.
- Activation gating is trust-critical: reject-with-specific-reason is a PRD acceptance scenario (`FEAT-014` edge case) - the rejection-reason capture is part of this IA.
- Audit viewing is read-only; tamper verification exists backend-side (`PHASE-4`) - note any status indicators the UI should surface as implications.
