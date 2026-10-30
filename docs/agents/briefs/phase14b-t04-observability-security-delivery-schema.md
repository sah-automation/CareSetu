# Brief - #765 Observability security signal, CSP aggregate, and alert delivery schema

**Ticket:** #765 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~6K

## Scope

Add an additive migration and models for minute-granular security signals, daily CSP aggregates, and durable alert delivery rows with one row per alert and channel.

- [ ] Security signal rows record signal kind, a hashed or empty subject key, and a count at minute granularity.
- [ ] CSP aggregates record daily directive, disposition, blocked source, and document path counts.
- [ ] Delivery rows have a unique constraint over alert and channel plus status, attempt, and next-retry fields.
- [ ] No phone number, free text, or raw CSP payload columns exist.
- [ ] The migration follows the current head and the cross-schema foreign key scan passes.

## Blocked by

- #764 - MOD-014 ops schema scaffold and single registration

## Read-list (in order)

1. Spec #761, security posture and alert routing decisions.
2. The observability schema models, the alert model, and the latest observability migrations.
3. The pseudonymous hashing scheme used for subject keys.

## Do NOT read

- docs/archive/
- The frontend.

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

- Raw CSP reports are never stored.
- Signal subject keys use the existing pseudonymous hashing scheme.
- No cross-schema foreign keys.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
