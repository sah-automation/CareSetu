# Brief - #771 Effective settings read with source and allowlist

**Ticket:** #771 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~9K

## Scope

Add an admin read of effective settings that returns each value with its source (database override, environment, or default), whether it is editable, and whether it requires a restart. Define the allowlist and cache effective values in process for 30 seconds.

- [ ] Precedence is database override, then environment, then default.
- [ ] Each value returns its source, editable flag, and restart-required flag.
- [ ] Only allowlisted operational AI knobs are editable.
- [ ] Provider, model, API key, base URL, signing keys, SMTP, Slack, and composition-root gates are read-only and never returned raw.
- [ ] Effective values are cached in process for 30 seconds.
- [ ] The route is admin-only.

## Blocked by

- #764 - MOD-014 ops schema scaffold and single registration
- #767 - Operator tier claim, gateway principal, admin guard, and me tier

## Read-list (in order)

1. Spec #761, configuration module and settings decisions.
2. The settings object, AI budget, timeout, and fallback reads.
3. The ops schema models and the existing cache patterns.

## Do NOT read

- docs/archive/
- The frontend settings page.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`

## Handoff notes

- Secrets and boot-time values are environment-only and read-only.
- Do not add a generic remote-config surface.
- The cache is per process; write invalidation lands in the next ticket.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
