# Brief - 441 Docs: blueprint + PRD status

**Ticket:** #441 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~2.5K tokens (budget 10K) - within budget

## Scope

Update the design blueprint and PRD so delivery matches docs: mark the `ui-blueprint.md` §6 doctor channel as implemented by PHASE-8.1 and record in the PRD acceptance notes that the patient pick-a-doctor step and the doctor console (queue, case workspace, prescription flow) are part of this delivery.

AC:

- [ ] UI blueprint doctor-channel section is marked implemented by PHASE-8.1
- [ ] PRD feature acceptance notes for the consultation / e-prescription features reflect the pick-a-doctor step and the doctor console delivery
- [ ] No contradiction remains between the blueprint, the PRD, and the roadmap PHASE-8.1 entry

## Read-list (in order)

1. `ui-blueprint.md` §6 doctor-channel section (surface IA, design system, cross-cutting patterns) - the surface to mark implemented (~900 tokens)
2. `project-prd.md` §4.4.1 (consultation orchestration) and §4.4.2 (e-prescription) - the acceptance notes to extend (~900 tokens)
3. `CONTEXT.md` glossary for care case / finalized pre-summary / verification declaration vocabulary (~350 tokens)
4. Issue #438 "User Stories" 1-26 and "Out of Scope" - what delivery now includes and excludes (~700 tokens)

## Do NOT read

- `docs/archive/`, roadmap, architecture matrices (handled in #439/#440), application code or tests.

## Baseline verify (must pass before the first edit)

- `npm run lint` on the untouched tree (docs-only change).

## Done-verify (acceptance criteria → commands)

- Diff review of the blueprint §6 status and the PRD acceptance notes.
- Grep shows no stale "Phase 14 doctor console" phrasing in blueprint or PRD.
- `npm run lint` passes.

## Handoff notes

- Keep status-phrasing consistent with what #439 writes into the roadmap and #440 into the matrices.
- The blueprint already fully spec's the doctor channel shell; this ticket only flips its status and reconciles PRD acceptance notes - it does not redesign anything.
