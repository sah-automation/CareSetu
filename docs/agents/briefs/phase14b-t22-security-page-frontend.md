# Brief - #783 Security page in the operator console

**Ticket:** #783 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~9K

## Scope

Add an operator-visible Security page to the Observability group showing auth and lockout trends, consent and rate-limit anomalies, CSP violations, prompt-injection counts, and webhook monitoring status.

- [ ] The Security page appears in the Observability navigation.
- [ ] All panels render from the security read API.
- [ ] Loading, empty, and error states are handled.
- [ ] Strings exist in both locale dictionaries.
- [ ] Tests cover the page and navigation entry.

## Blocked by

- #782 - Security summary and signal read API

## Read-list (in order)

1. The operator observability page pattern, the navigation config, the chart components, and the i18n dictionaries.
2. The security read API response shapes.

## Do NOT read

- docs/archive/
- Backend detector internals.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- Security is operator-visible, not admin-only.
- Use the shared panel frame.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
