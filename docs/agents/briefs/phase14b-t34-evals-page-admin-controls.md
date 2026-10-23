# Brief - #795 Evals page admin controls

**Ticket:** #795 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~9K

## Scope

Add admin controls to the Evals page for creating, editing, and activating dataset versions, starting capped judge runs, and applying human labels.

- [ ] Admin-only controls are hidden from non-admins.
- [ ] Admins can create, edit, and activate dataset versions.
- [ ] Admins can start a judge run with the budget cap visible.
- [ ] Operators can apply human labels.
- [ ] Restart and validation errors are shown clearly.
- [ ] Strings exist in both locales.

## Blocked by

- #788 - Evaluation dataset validation and PHI-pattern rejection
- #790 - Confidence calibration and prescription-draft accuracy evaluators
- #791 - Human labels on golden examples
- #794 - Evals page read-only view

## Read-list (in order)

1. The Evals page, the dataset and judge APIs, the human label API, and the session tier.

## Do NOT read

- docs/archive/
- Backend internals beyond the APIs.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- Active versions stay immutable.
- Do not expose secrets or provider controls.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
