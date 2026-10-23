# Brief - #764 MOD-014 ops schema scaffold and single registration

**Ticket:** #764 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~9K

## Scope

Add the MOD-014 ops private schema with settings, setting history, feature flags, and an outbox. Register it exactly once across the module registry, worker registration, scaffold metadata, boundary checker, schema-count documentation, and tests.

- [ ] An init migration creates the ops schema tables for settings, history, feature flags, and outbox.
- [ ] The module is registered in the module schema list, worker register list, and scaffold metadata.
- [ ] The boundary checker passes and the schema-count documentation and tests report the new module.
- [ ] The worker register order matches the module schema order.
- [ ] The migration check reports a single head.

## Blocked by

- #763 - IAM operator profile schema and admin backfill

## Read-list (in order)

1. Spec #761, configuration module decisions.
2. The module scaffold generator and the module schema list.
3. The worker register list and the boundary checker.
4. The coding standard module layout and the observability module as prior art.

## Do NOT read

- docs/archive/
- Domain modules other than the scaffold pattern.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`
- `npm run migration-check`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run migration-check`
- `npm run typecheck`

## Handoff notes

- MOD-014 owns no domain tables, no PHI, and no secrets.
- This is the thirteenth private module schema.
- Do not add settings behavior in this ticket; only the scaffold and registration.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
