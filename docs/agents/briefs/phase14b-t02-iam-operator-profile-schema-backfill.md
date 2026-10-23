# Brief - #763 IAM operator profile schema and admin backfill

**Ticket:** #763 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~6K

## Scope

Add an IAM operator profile table keyed by identity with tier, active state, MFA failure counters, MFA lockout time, and creator/updater references. The migration backfills every existing identity with an active admin role grant so the current operator group is not locked out.

- [ ] A new operator profile table exists with tier, active state, MFA counters, lockout time, and creator/updater references.
- [ ] The migration backfills every existing identity to an active admin operator profile.
- [ ] New profile rows default to the non-admin operator tier in the model and service layer.
- [ ] The migration downgrades cleanly and leaves no cross-schema foreign keys.
- [ ] The migration check reports a single head.

## Blocked by

None - can start immediately.

## Read-list (in order)

1. Spec #761, operator identity and authority decisions.
2. The IAM schema models and the current migration head.
3. The module migration naming and raw-SQL pattern.
4. ADR-0003 and ADR-0025 for module and schema isolation.

## Do NOT read

- docs/archive/
- The observability and frontend modules.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`
- `npm run migration-check`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run migration-check`
- `npm run typecheck`

## Handoff notes

- The tier is not added to the shared identity row.
- The backfill is migration-only. Do not add runtime backfill code.
- Do not change existing role grant semantics.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
