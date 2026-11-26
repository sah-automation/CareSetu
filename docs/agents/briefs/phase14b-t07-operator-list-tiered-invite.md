# Brief - #768 Admin operator list and tiered invite

**Ticket:** #768 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~8K

## Scope

Admins can list operators with masked phone, tier, active state, MFA state, and creation date, and invite an operator at a chosen tier. New invites default to the non-admin operator tier.

- [ ] The operator list is admin-only and returns masked phone, tier, active, MFA, and created date.
- [ ] A non-admin token receives the shared 403 envelope.
- [ ] Invite accepts a tier and defaults to operator when omitted.
- [ ] Invite, tier, and operator state changes emit audit events.
- [ ] Tests cover admin allow, non-admin deny, and invite defaults.

## Blocked by

- #767 - Operator tier claim, gateway principal, admin guard, and me tier

## Read-list (in order)

1. Spec #761, operator identity and user management decisions.
2. The IAM identity facade create-operator path, the operator invite route, and the masking helper.
3. The audit event pattern for IAM changes.

## Do NOT read

- docs/archive/
- Partner verification routes.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`

## Handoff notes

- Phone numbers are masked in every response.
- The existing operator-invites-operator path remains, but only admins may use it.
- Do not add public signup.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
