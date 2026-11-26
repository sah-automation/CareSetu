# Brief - #799 Settings Notifications section

**Ticket:** #799 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~7K

## Scope

Add the Notifications section with the routing matrix, recipients, channel toggles, test send, recent delivery attempts, and redelivery.

- [ ] Routing and recipients are editable.
- [ ] Channel enable and disable are visible and editable.
- [ ] Test send works and reports the result.
- [ ] Recent deliveries are visible and failed deliveries can be redelivered.
- [ ] Strings exist in both locales.

## Blocked by

- #774 - Notification routing, recipients, and channel settings
- #784 - Durable alert delivery core, retries, and redelivery
- #797 - Settings page shell and AI read section

## Read-list (in order)

1. The Settings shell, the notification routing API, and the delivery status and redelivery APIs.

## Do NOT read

- docs/archive/
- The delivery worker internals.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- Set blank secrets.
- Show disabled channel state clearly.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
