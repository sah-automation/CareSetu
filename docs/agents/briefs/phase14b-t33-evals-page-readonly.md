# Brief - #794 Evals page read-only view

**Ticket:** #794 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~9K

## Scope

Add an operator Evals page showing the active dataset, run control and progress, judge scores, agreement, labeling view, and the synthetic-only statement.

- [ ] The Evals page appears in the Observability navigation.
- [ ] Dataset, run progress, scores, agreement, and labeling are visible.
- [ ] The synthetic-only statement is visible.
- [ ] Loading, empty, and error states are handled.
- [ ] Strings exist in both locales.

## Blocked by

- #793 - Evaluation read API

## Read-list (in order)

1. The operator observability page pattern, the navigation config, the chart components, and the i18n dictionaries.
2. The eval read API shapes.

## Do NOT read

- docs/archive/
- Backend judge internals.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- Evals is operator-visible.
- The synthetic-only copy is mandatory.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
