# Brief - #796 Admin-only navigation filtering and permission state

**Ticket:** #796 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~9K

## Scope

Add an admin-only flag to the navigation item shape and filter it consistently in the sidebar, collapsed rail, mobile tab bar, and mobile More sheet. Direct navigation to an admin-only page renders a clear permission state. Hide Settings from non-admins.

- [ ] The nav item shape carries an admin-only flag.
- [ ] Admin-only items are filtered in every navigation surface.
- [ ] Direct navigation to an admin-only page renders the permission state.
- [ ] Settings is hidden from non-admins and visible to admins.
- [ ] Existing navigation behavior is unchanged for non-admin items.
- [ ] Tests cover desktop, collapsed rail, mobile tabs, and More sheet.

## Blocked by

- #767 - Operator tier claim, gateway principal, admin guard, and me tier

## Read-list (in order)

1. The navigation config and its consumers, the auth context, and the me response tier.
2. The i18n dictionaries and the navigation tests.

## Do NOT read

- docs/archive/
- The observability page panels.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- Backend authorization remains the authority; this is UX filtering.
- Use the tier from the me response.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
