# Brief - #774 Notification routing, recipients, and channel settings

**Ticket:** #774 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~7K

## Scope

Add admin settings for per-alert-kind routing to Slack, email, or none, email recipients, and channel enable or disable. Slack and SMTP secrets remain environment-only.

- [ ] Routing is configurable per alert kind.
- [ ] Recipients and channel enable or disable are configurable.
- [ ] Invalid routing or recipients are rejected with the shared error envelope.
- [ ] No secret value is returned raw or editable.
- [ ] Changes record history and emit audit events.

## Blocked by

- #772 - Allowlisted settings writes with history and audit

## Read-list (in order)

1. Spec #761, alert routing decisions.
2. The ops settings write engine and the alert kind vocabulary.
3. The integration standard for environment-only secrets.

## Do NOT read

- docs/archive/
- The delivery worker.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`

## Handoff notes

- Slack webhook URLs and SMTP credentials are environment-only.
- Delivery is gated off by default in a later ticket.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
