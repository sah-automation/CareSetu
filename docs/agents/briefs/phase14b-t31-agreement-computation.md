# Brief - #792 Judge and human agreement computation

**Ticket:** #792 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~5K

## Scope

Compute agreement per evaluator as count, mean absolute error, within-tolerance share, and kappa for boolean evaluators.

- [ ] Agreement is computed per evaluator.
- [ ] Count, mean absolute error, within-tolerance share, and kappa are correct for numeric and boolean cases.
- [ ] Missing pairs produce a defined empty state.
- [ ] The read response states that agreement is synthetic-only.

## Blocked by

- #790 - Confidence calibration and prescription-draft accuracy evaluators
- #791 - Human labels on golden examples

## Read-list (in order)

1. Spec #761, agreement decisions.
2. The evaluation score model and the evaluation domain.

## Do NOT read

- docs/archive/
- The frontend.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run typecheck`

## Handoff notes

- Synthetic-only by construction.
- No production judge agreement.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
