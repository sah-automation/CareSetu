# Brief - #790 Confidence calibration and prescription-draft accuracy evaluators

**Ticket:** #790 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~7K

## Scope

Add the confidence calibration and prescription-draft accuracy judge evaluators, including partial-failure handling when one evaluator fails and the others succeed.

- [ ] Calibration and prescription accuracy scores are produced.
- [ ] A failed evaluator does not discard successful scores.
- [ ] Partial failure is recorded on the run.
- [ ] Scores remain advisory and carry non-PHI metadata.
- [ ] Tests cover both evaluators and partial failure.

## Blocked by

- #789 - LLM judge run worker and completeness evaluator

## Read-list (in order)

1. Spec #761, judge evaluator decisions.
2. The judge run domain, the evaluation domain, and the AI gateway fake.

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

- Use the same run reference and metadata rules.
- Do not add production-content judging.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
