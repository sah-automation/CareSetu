# Brief - #767 Operator tier claim, gateway principal, admin guard, and me tier

**Ticket:** #767 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~9K

## Scope

Carry an optional operator tier claim in operator access tokens, re-derive it on refresh, expose it on the gateway principal and the authenticated me response, and add an admin guard that returns the shared 403 envelope. Missing or unknown tiers fail admin routes closed.

- [ ] Operator access tokens include the tier claim; patient and partner tokens omit it.
- [ ] Refresh re-derives the tier from the operator profile.
- [ ] The gateway principal exposes the tier and the me response includes it.
- [ ] The admin guard allows admins and rejects operator, missing, and unknown tiers with the shared 403 envelope.
- [ ] Existing operator reads and alert acknowledgements stay on the operator guard.
- [ ] Tests cover allow, deny, refresh, and missing claim.

## Blocked by

- #763 - IAM operator profile schema and admin backfill

## Read-list (in order)

1. Spec #761, operator identity and authority decisions.
2. The IAM JWT domain, session issue and refresh, and the gateway principal and RBAC modules.
3. The IAM me route and the shared error envelope.

## Do NOT read

- docs/archive/
- The observability read routes except as guard prior art.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`

## Handoff notes

- Reads use the token claim; admin writes re-check the profile in a later ticket.
- The 15 minute access-token lifetime is the staleness bound.
- Do not add an admin role to the shared role grant table.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
