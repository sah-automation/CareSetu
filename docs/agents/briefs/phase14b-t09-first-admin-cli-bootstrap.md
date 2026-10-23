# Brief - #770 First-admin CLI promotion

**Ticket:** #770 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~5K

## Scope

Add a CLI command that promotes an existing identity to admin so a fresh deployment has a first admin without public signup.

- [ ] The command promotes an existing identity to the admin tier.
- [ ] The command is idempotent and refuses a missing identity with a clear error.
- [ ] The invocation is documented for deployment.
- [ ] No public HTTP route is added.

## Blocked by

- #763 - IAM operator profile schema and admin backfill

## Read-list (in order)

1. Spec #761, first-admin bootstrap decision.
2. The demo seed script and its invocation in deployment.
3. The IAM identity facade and the operator profile model.

## Do NOT read

- docs/archive/
- The frontend.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run typecheck`

## Handoff notes

- This is a deployment bootstrap tool, not a signup path.
- Reuse the existing profile and role-grant write seams.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
