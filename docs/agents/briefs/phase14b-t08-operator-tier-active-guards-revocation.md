# Brief - #769 Operator tier and active-state changes with last-admin guards

**Ticket:** #769 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~9K

## Scope

Admins can promote or demote an operator and deactivate or reactivate an operator. Demotion and deactivation revoke active sessions. The last active admin and self-demotion or self-deactivation are refused. Every change is audited.

- [ ] Tier changes persist, revoke active sessions, and apply immediately to admin writes.
- [ ] Deactivation revokes sessions and blocks login; reactivation restores access.
- [ ] Demoting or deactivating the last active admin is refused.
- [ ] Self-demotion and self-deactivation are refused.
- [ ] Failures use the shared error envelope.
- [ ] Every change emits an audit event.

## Blocked by

- #768 - Admin operator list and tiered invite

## Read-list (in order)

1. Spec #761, last-admin and revocation decisions.
2. The operator profile model, session revocation, and the IAM facade.
3. The audit event pattern and the shared error envelope.

## Do NOT read

- docs/archive/
- The frontend.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`

## Handoff notes

- Admin writes re-check the profile so demotion is immediate.
- Reads use the token claim and converge within the access-token lifetime.
- Do not allow an operator to change their own tier or active state.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
