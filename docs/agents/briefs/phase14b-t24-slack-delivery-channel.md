# Brief - #785 Slack alert delivery channel

**Ticket:** #785 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~5K

## Scope

Add a Slack HTTP webhook delivery channel behind an environment-only secret and a default-off gate.

- [ ] The adapter posts the delivery payload to the Slack webhook.
- [ ] The gate off path is a no-op.
- [ ] A missing secret fails safely without leaking it.
- [ ] Tests use a fake HTTP adapter.
- [ ] Delivery core uses the Slack channel when enabled.

## Blocked by

- #784 - Durable alert delivery core, retries, and redelivery

## Read-list (in order)

1. The delivery channel protocol and the delivery core.
2. The settings gate pattern and the third-party integration standard.

## Do NOT read

- docs/archive/
- SMTP.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run typecheck`

## Handoff notes

- The webhook URL is environment-only.
- No secret appears in the database or UI.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
