# Brief - #784 Durable alert delivery core, retries, and redelivery

**Ticket:** #784 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~9K

## Scope

Add durable delivery rows per alert and channel, a router job for newly opened alerts using notification routing, a skip-locked drainer with exponential backoff, terminal failure, delivery status, redelivery, and test delivery. A delivery-failure alert is raised but never routed back into the failing channel.

- [ ] One delivery row exists per alert and channel.
- [ ] The router creates rows for new alerts using routing settings.
- [ ] The drainer uses skip-locked semantics and exponential backoff.
- [ ] Terminal failures are visible and an admin can redeliver.
- [ ] Admins can send a test notification.
- [ ] The delivery-failure alert is not routed to the failing channel.
- [ ] The feature is gated off by default.

## Blocked by

- #765 - Observability security signal, CSP aggregate, and alert delivery schema
- #774 - Notification routing, recipients, and channel settings

## Read-list (in order)

1. Spec #761, alert routing and delivery decisions.
2. The alert model and kinds, the worker scheduler, and the dispatcher skip-locked pattern.
3. The notification routing settings and the console link format.

## Do NOT read

- docs/archive/
- The Slack and SMTP adapters.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`

## Handoff notes

- Payloads carry severity, kind, title, alert id, and a console link only.
- No PHI, phone number, or free text in payloads.
- Use a fake channel adapter in tests.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
