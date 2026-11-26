# Brief - 527 Combined /code-review pass for #520

**Ticket:** #527 · **Parent:** #520 · **Refreshed:** 2026-09-23
**Reading surface:** ~6K tokens base (budget 10K) - diffs of #521-#526 dominate; brief applies at review time

## Scope

Review the complete #520 implementation (#521-#526) as one change set using the `/code-review` skill - both axes: does it follow this repo's documented standards, and does it match spec #520 (user stories, implementation/testing decisions, out-of-scope)? Fix any bugs or spec gaps found.

Acceptance criteria:

- `/code-review` run across the full #520 change set (standards + spec axes)
- Findings fixed or explicitly dispositioned
- `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green after fixes

## Read-list (in order)

1. Spec #520 in full - the contract to judge against (~3K tokens)
2. The `/code-review` skill (run it first; it drives both axes and parallel sub-agents) (~1K)
3. `docs/standards/coding-standards.md` and `docs/standards/error-handling-observability.md` (surface-adjacent) - the standards axis (~1.5K)
4. The diffs of #521-#526 as they land - the code axis; read only within the change set

## Do NOT read

- `docs/archive/`
- Unrelated modules outside the #521-#526 change set (a finding that pulls you outside is a re-cut signal, not a rabbit hole)
- Backend code unless a change set touches it (it should not: #520 is frontend-only per spec)

## Baseline verify (must pass before the first edit)

- `npm run typecheck`
- `npm run lint`
- `npm run test:unit:frontend` - note: 1 pre-existing failure in the doctor case pre-summary test at HEAD, unrelated to #520; attribute only new failures to the change set

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend`, `npm run lint`, `npm run typecheck` green after any fixes
- `npm run migration-check` passes only if any ticket introduced schema work (spec says none)

## Handoff notes

- The review is horizontal (all of #520 at once) by design - the last gate before the parent closes.
- Match the tracing-list conventions from spec "Further Notes": verify bundle guardrail and bilinguality are intact in the combined tree.
- Do not close or modify parent #520; report the review summary there if asked.
