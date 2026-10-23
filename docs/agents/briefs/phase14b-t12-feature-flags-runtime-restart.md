# Brief - #773 Feature flags with runtime and restart-required typing

**Ticket:** #773 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~7K

## Scope

Add typed feature flags that are either runtime or restart-required. Runtime flags are admin-editable; restart-required flags are read-only with an explanation. Flag reads are operator-visible.

- [ ] Flags carry a runtime or restart-required type.
- [ ] Operators can read flags.
- [ ] Admins can edit runtime flags only.
- [ ] Writing a restart-required flag is refused with a clear error.
- [ ] Changes record history and emit audit events.
- [ ] Tests cover runtime write, restart refusal, and operator read.

## Blocked by

- #771 - Effective settings read with source and allowlist

## Read-list (in order)

1. Spec #761, feature flag decisions.
2. The ops models and settings cache.
3. The composition-root gates that must stay restart-required.

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

- No per-user or percentage rollout.
- Only runtime flags are editable.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
