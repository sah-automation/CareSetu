# Brief - 439 Docs: roadmap traceability

**Ticket:** #439 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~3.5K tokens (budget 10K) - within budget

## Scope

Add a `PHASE-8.1` section to the implementation roadmap (following the `PHASE-2.5`/`PHASE-2.6` precedent), correct the channel-phase wording so the doctor console UI is no longer billed as Phase 14 work, extend the §3.1/§3.2/§3.3 traceability matrices with PHASE-8.1 rows, and mark the prototype plan's Phase 8 row as production-ized by this phase.

AC:

- [ ] Roadmap gains a `PHASE-8.1` section describing this phase's strips and seams
- [ ] The channel-phase wording claiming the doctor console lands in Phase 14 is corrected
- [ ] Phased traceability rows (§3.1 feature↔module↔phase, §3.2 actor/interface↔phase, §3.3 module↔primary-build-phase) gain PHASE-8.1 entries
- [ ] Prototype plan Phase 8 row is marked production-ized by this phase

## Read-list (in order)

1. `implementation-roadmap.md` §1.2 phase table and the `PHASE-2.5`/`PHASE-2.6` delivered-insert precedent sections - the pattern to copy for the new insert (~600 tokens)
2. `implementation-roadmap.md` §2.8 Phase 8 delivered/hardening section and the Phase 14 channel phrasing to correct - scope of the new entry + what to un-say (~900 tokens)
3. `implementation-roadmap.md` §3.1/§3.2/§3.3 traceability matrices - where the new rows go (~1500 tokens)
4. `CONTEXT.md` "Provider directory" glossary + `prototype/PLAN.md` Phase 8 row - vocabulary and the status flip (~350 tokens)
5. Issue #438 "Further Notes" bullet - the exact doc claims to satisfy (~200 tokens)

## Do NOT read

- `docs/archive/`, any application code, test files, the PRD feature sections, other phases' roadmap sections.

## Baseline verify (must pass before the first edit)

- `npm run lint` on the untouched tree (docs-only change; whitespace/prettier gate).

## Done-verify (acceptance criteria → commands)

- Grep the roadmap for `PHASE-8.1` - the section and the §3 rows exist.
- Grep for the Phase-14 doctor-console claim - it no longer reads that way.
- `npm run lint` passes after the edit.
- Diff review of `prototype/PLAN.md` Phase 8 row status.

## Handoff notes

- Source of truth for the section content is issue #438 (strips: pick-a-doctor, doctor console queue/case workspace/prescription, six backend deltas, fee seam).
- Architecture matrices and blueprint/PRD notes are handled in sibling tickets #440/#441 - do not touch those files.
