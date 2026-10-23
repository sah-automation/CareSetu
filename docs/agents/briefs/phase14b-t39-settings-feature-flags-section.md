# Brief - #800 Settings Feature flags section

**Ticket:** #800 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~6K

## Scope

Add the Feature flags section with runtime flags editable and restart-required flags read-only with an explanation.

- [ ] All flags are listed with their type.
- [ ] Runtime flags are editable.
- [ ] Restart-required flags are read-only with an explanation.
- [ ] History is visible.
- [ ] Strings exist in both locales.

## Blocked by

- #773 - Feature flags with runtime and restart-required typing
- #797 - Settings page shell and AI read section

## Read-list (in order)

1. The Settings shell, the feature flag API, and the i18n dictionaries.

## Do NOT read

- docs/archive/
- Composition-root gate internals.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- No per-user rollout controls.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
