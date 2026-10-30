# Brief - #787 Versioned evaluation dataset API

**Ticket:** #787 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~8K

## Scope

Seed an active dataset version from the existing golden dataset, allow draft creation, cloning, and editing, and allow activation and retirement. Active versions cannot be edited in place.

- [ ] The seed is idempotent and creates the active version from the golden dataset.
- [ ] Admins can create, clone, and edit draft versions.
- [ ] Admins can activate a version, which retires the old active version.
- [ ] Editing an active version is refused.
- [ ] The routes are admin-only.

## Blocked by

- #766 - Evaluation dataset, run, and judge score schema
- #767 - Operator tier claim, gateway principal, admin guard, and me tier

## Read-list (in order)

1. Spec #761, evaluation dataset decisions.
2. The golden dataset, the eval schema models, and the observability routes and facade.
3. The admin guard and the shared error envelope.

## Do NOT read

- docs/archive/
- Production content paths.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`

## Handoff notes

- Synthetic data only.
- Active versions are immutable.
- Do not copy production content.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
