# Brief - 454 Review-all pass (code-review + fix bugs)

**Ticket:** #454 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

A closing review pass over the combined PHASE-8.1 implementation after all tickets merge: run the code-review skill against the whole phase's diff (Standards axis and Spec axis) and fix any bugs or gaps the review surfaces. Green is promised here, not per-ticket.

AC:

- [ ] A code-review pass over all merged PHASE-8.1 changes finds no open standards or spec violations
- [ ] Any bugs found by the review are fixed and re-verified
- [ ] The final tree passes the full repo harness (unit, lint, typecheck)

## Read-list (in order)

1. The `code-review` skill (D:\Dev\tools\opencode\config\opencode\skills\code-review\SKILL.md) - the two-axis review process to run (~800 tokens)
2. The combined PHASE-8.1 diff from the merge-base (changes across tickets #439-#453) - the object of review
3. `docs/standards/coding-standards.md`, `docs/standards/api-standards.md`, `docs/standards/security-phii-standards.md` - the Standards axis (~3K tokens)
4. The originating tickets' acceptance criteria (#439-#453 bodies) - the Spec axis (~2K tokens)
5. `CONTEXT.md` build-session protocol + change-set summary (~500 tokens)

## Do NOT read

- `docs/archive/`, unrelated phases' diffs, prototype, docs tickets' internals beyond what the changes touched.

## Baseline verify (must pass before the first edit)

- `npm run test:unit` (expect only the 3 known pre-existing dev-OTP backend env failures), `npm run lint`, `npm run typecheck`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit` (backend + frontend) green apart from the recorded pre-existing env failures; `npm run lint` and `npm run typecheck` clean; review report shows no open violations.

## Handoff notes

- Blockers: all of #439-#453 must be closed/merged before this runs.
- The 3 pre-existing backend dev-OTP failures are environmental baseline, not regressions - flag a fix only if they change.
- Run review as two parallel sub-agents (Standards | Spec) per the code-review skill and report side by side.
