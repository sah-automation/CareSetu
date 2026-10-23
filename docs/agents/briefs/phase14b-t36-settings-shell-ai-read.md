# Brief - #797 Settings page shell and AI read section

**Ticket:** #797 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~8K

## Scope

Replace the Settings placeholder with an admin Settings page shell and an AI section that shows effective values with source badges and restart-required badges.

- [ ] The Settings page has the four section shell.
- [ ] The AI section shows effective values.
- [ ] Source and restart-required badges are visible.
- [ ] The page is admin-only and hidden from non-admins.
- [ ] Strings exist in both locales.

## Blocked by

- #771 - Effective settings read with source and allowlist
- #796 - Admin-only navigation filtering and permission state

## Read-list (in order)

1. The Settings placeholder, the observability page pattern, the operator client, and the i18n dictionaries.
2. The effective settings read API.

## Do NOT read

- docs/archive/
- The write API.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- Remove the placeholder copy.
- Read-only in this ticket.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
