# Brief - 684 Combined review of the #673 doctor console overhaul

**Ticket:** #684 · **Parent:** #673 · **Refreshed:** 2026-10-09
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

After the implementation tickets land, run the repo's two-axis `/code-review` over the combined `#673` change set (Standards against `docs/standards/*` and Spec against spec `#673`) and fix any bugs, regressions or standard violations it finds. This is the batch's closing gate and must leave the full frontend verification suite green.

## Acceptance criteria

- [ ] `/code-review` run over the combined `#673` change set against spec `#673`
- [ ] Findings triaged; real bugs, regressions and standard violations fixed
- [ ] The full done-verify suite is green after the fixes
- [ ] A short note of what was found and fixed is posted on this ticket

## Read-list (in order)

1. The `code-review` skill - the two-axis procedure to run. (~500 tokens)
2. Spec #673 - the full spec, including the out-of-scope list, for the Spec axis. (~4K, but skim for the changed surfaces)
3. This batch's briefs and the landed diffs across the ten implementation tickets. (~varies)
4. `docs/standards/*` - the standards the Standards axis checks (coding, api, error-handling/observability, security-PHII as they apply to a frontend-only change). (~as needed)

## Do NOT read

- `docs/archive/`.
- Backend modules - this batch is frontend-only.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - confirmed green 2026-10-09 (134 files / 2157 tests passed).
- `npm run typecheck:frontend` - confirmed green 2026-10-09.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- **Two axes, one report.** Review against the spec AND the standards side by side; the whole point is catching both a spec miss and a standards drift across the combined set, which per-ticket reviews miss.
- **Fix with evidence.** Only fix real bugs, regressions and standard violations; re-run the full suite after each fix. If a "finding" is by-design per the spec (for example the deliberate service-area non-rendering or the frontend-only constraint), record why it stands rather than changing it.
- **Do not expand scope.** The out-of-scope list in #673 (backend, pagination, other focus-rings, design tokens, consent semantics, prototype folder) still binds this review.
- **No em-dashes anywhere** (lint-gated) - use simple dashes.
