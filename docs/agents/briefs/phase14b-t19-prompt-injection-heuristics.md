# Brief - #780 Prompt-injection heuristics before AI egress

**Ticket:** #780 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~7K

## Scope

Run advisory prompt-injection heuristics before AI egress. Detect instruction override, system-prompt probing, exfiltration, and tool-call patterns. Emit categories and a score only, with no content, and do not block the pipeline in this batch.

- [ ] Positive and negative cases are detected for the four categories.
- [ ] The emitted event carries categories and a score only.
- [ ] The check runs before AI egress.
- [ ] The result is advisory and does not block the pipeline.
- [ ] A security signal is recorded without content.

## Blocked by

- #777 - Security signal aggregation consumers

## Read-list (in order)

1. Spec #761, prompt-injection decisions.
2. The intake AI egress point, the event registry, and the security signal model.

## Do NOT read

- docs/archive/
- The frontend.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`

## Handoff notes

- Never store patient text in the event or signal.
- Do not block the pipeline in this batch.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
