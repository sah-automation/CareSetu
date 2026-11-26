# Brief - #772 Allowlisted settings writes with history and audit

**Ticket:** #772 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~9K

## Scope

Admins can write the allowlisted operational AI knobs with bounds, idempotency, setting history, an audit event, and cache invalidation.

- [ ] Only allowlisted keys are writable.
- [ ] Values are bounded and validated with the shared error envelope.
- [ ] Writes are idempotent through the existing mechanism.
- [ ] Each write records history and emits an audit event.
- [ ] The local effective-settings cache is invalidated.
- [ ] A non-admin receives the shared 403 envelope.

## Blocked by

- #771 - Effective settings read with source and allowlist

## Read-list (in order)

1. Spec #761, settings write decisions.
2. The ops facade and models, the idempotency mechanism, and the audit event pattern.
3. The AI settings reads in the intake module.

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

- Provider, model, API key, and base URL stay read-only.
- No secret is stored in Postgres.
- Do not add restart-required keys to the write allowlist.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
