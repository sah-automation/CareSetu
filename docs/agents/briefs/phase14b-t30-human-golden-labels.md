# Brief - #791 Human labels on golden examples

**Ticket:** #791 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~5K

## Scope

Let operators label golden dataset examples with source human, observation kind golden, and the same evaluator names used by code and judge.

- [ ] Operators can create and update human labels.
- [ ] Labels use source human and observation kind golden.
- [ ] Evaluator names match the code and judge vocabulary.
- [ ] Non-operators are refused.
- [ ] Tests cover creation, update, and guard behavior.

## Blocked by

- #766 - Evaluation dataset, run, and judge score schema

## Read-list (in order)

1. Spec #761, human label decisions.
2. The evaluation score model, the eval routes, and the operator guard.

## Do NOT read

- docs/archive/
- The judge run.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`

## Handoff notes

- Operators can label; admins manage datasets.
- No production content.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
