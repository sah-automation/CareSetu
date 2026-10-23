# Brief - #793 Evaluation read API

**Ticket:** #793 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~7K

## Scope

Add an operator read API for the active dataset, run progress, judge scores, agreement, and the synthetic-only marker.

- [ ] Routes are operator-guarded.
- [ ] Responses cover the active dataset, run progress, scores, and agreement.
- [ ] The synthetic-only marker is present.
- [ ] No PHI is returned.
- [ ] Tests cover shapes and guard behavior.

## Blocked by

- #787 - Versioned evaluation dataset API
- #792 - Judge and human agreement computation

## Read-list (in order)

1. Spec #761, eval read decisions.
2. The observability read facade and routes, the eval models, and the agreement domain.

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

- Read-only.
- State synthetic-only in the response.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
