# Brief - #786 SMTP alert delivery channel

**Ticket:** #786 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~5K

## Scope

Add an optional SMTP email delivery channel using the standard library SMTP client in a background thread with TLS, behind environment-only credentials and a default-off gate.

- [ ] The adapter sends the delivery payload by email.
- [ ] The gate off path is a no-op.
- [ ] A missing credential fails safely without leaking it.
- [ ] Tests use a fake SMTP adapter.
- [ ] Delivery core uses the email channel when enabled.

## Blocked by

- #784 - Durable alert delivery core, retries, and redelivery

## Read-list (in order)

1. The delivery channel protocol and the delivery core.
2. The settings gate pattern and the third-party integration standard.

## Do NOT read

- docs/archive/
- Slack.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run typecheck`

## Handoff notes

- Credentials are environment-only.
- Email is optional.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
