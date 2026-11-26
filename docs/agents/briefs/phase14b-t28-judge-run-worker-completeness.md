# Brief - #789 LLM judge run worker and completeness evaluator

**Ticket:** #789 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~9K

## Scope

Run the LLM judge in the worker over the active synthetic dataset with a dedicated AI task type, a budget check and cap, temperature zero, strict JSON output, one retry on parse failure, and scores stored with source judge and a run reference. The first evaluator is completeness. Scores are advisory.

- [ ] The judge runs in the worker, not the request path.
- [ ] Budget is checked before the run and capped during it.
- [ ] The AI call uses a dedicated task type, temperature zero, and strict JSON.
- [ ] One parse failure is retried.
- [ ] Scores are stored with source judge and a run reference.
- [ ] Scores never gate approval.

## Blocked by

- #766 - Evaluation dataset, run, and judge score schema

## Read-list (in order)

1. Spec #761, judge run decisions.
2. The AI gateway protocol and fake, the budget meter, the eval models, and the worker job pattern.

## Do NOT read

- docs/archive/
- The frontend evals page.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`

## Handoff notes

- Use the existing AI usage and cost pipeline.
- No PHI in judge metadata.
- Advisory only.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
