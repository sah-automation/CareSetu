# Brief - 371 T07 Document scope decision + separate unrelated commits

**Ticket:** #371 Â· **Parent:** #364 Â· **Refreshed:** 2026-09-09
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

Two cleanup tasks: (1) document the save_patient_pre_summary_edits scope deviation as a conscious decision, (2) separate unrelated partner-module changes and doc-only briefs from the Phase 7 commit so the diff is clean and reviewable.

Acceptance criteria (from ticket):

- [ ] Phase 7 release notes acknowledge save_patient_pre_summary_edits as delivered beyond Phase 7 scope boundary - kept because fully implemented, tested, and useful
- [ ] Commit fd682a1 split via interactive rebase into: Phase 7 T17 code, documentation briefs, partner-module touch-ups (or revert partner changes in follow-up commit if rebase not possible)
- [ ] Partner route tests pass after cleanup: test_partner_credentials_route.py, test_partner_verification_route.py, test_partner_rejection_recovery_route.py

## Read-list (in order)

1. `git log --oneline -30` for the Phase 7 T17 area and commit fd682a1 - to see what was bundled together (~0.5K tokens)
2. `git show fd682a1 --stat` - the file-level split surface (which files are Phase 7 code, which are docs briefs, which are partner-module changes) (~0.5K tokens)
3. `docs/roadmap/implementation-roadmap.md` Â§phase-7 - the scope boundary that save_patient_pre_summary_edits crossed (~1K tokens)
4. Where Phase 7 release notes live - to add the "delivered beyond scope" note (~0.3K tokens)
5. `apps/backend/modules/intake/facade.py` - `save_patient_pre_summary_edits` (line 474) to confirm the delivered scope (~0.7K tokens)

## Do NOT read

- The pipeline adapter or other intake internals
- Frontend sources, `docs/archive/`
- Deep partner module internals (only the affected partner route tests matter for the done-gate)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 1579 passed (verified 2026-09-09)
- `npm run typecheck:backend` - mypy strict clean (verified 2026-09-09)
- Note: full `npm run typecheck` currently fails only on the stale Next.js generated artifact `.next/dev/types/routes.d.ts` (not source). Ignore it; confirm with `typecheck:backend`.

## Done-verify (acceptance criteria -> commands)

- `git log --oneline` shows clean separation (interactive rebase) or a follow-up revert commit for partner changes
- `npm run test:unit:backend` - test_partner_credentials_route.py, test_partner_verification_route.py, test_partner_rejection_recovery_route.py all pass
- `npm run typecheck` clean

## Handoff notes

- Independent - no blockers.
- Per repo AGENTS.md and the to-tickets skill: do NOT modify or close the parent issue #364; this ticket only cleans the commit history and documents the scope decision.
- The recommended decision is to KEEP save_patient_pre_summary_edits (it is fully implemented, tested, useful) and document it as "delivered beyond scope" rather than remove it.
- If the Phase 7 commit was already pushed, an interactive rebase that rewrites shared history is risky - prefer the follow-up revert approach for partner-module changes. Follow resolving-merge-conflicts / normal git hygiene; do not force-push without confirmation.
