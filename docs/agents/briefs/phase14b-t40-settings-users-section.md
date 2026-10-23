# Brief - #801 Settings Users section

**Ticket:** #801 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~7K

## Scope

Add the Users section with the operator list, invite at a chosen tier, promote or demote, and deactivate or reactivate, with masked phones.

- [ ] Operators are listed with masked phone, tier, active state, and MFA state.
- [ ] Invites default to operator.
- [ ] Tier changes and active-state changes work.
- [ ] Last-admin and self-change errors are shown clearly.
- [ ] Strings exist in both locales.

## Blocked by

- #768 - Admin operator list and tiered invite
- #769 - Operator tier and active-state changes with last-admin guards
- #797 - Settings page shell and AI read section

## Read-list (in order)

1. The Settings shell and the operator user management APIs.
2. The session tier for admin-only controls.

## Do NOT read

- docs/archive/
- IAM internals beyond the APIs.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- Keep phones masked.
- Do not add public signup.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
