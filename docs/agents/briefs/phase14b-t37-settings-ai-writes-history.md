# Brief - #798 Settings AI writes and history

**Ticket:** #798 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~6K

## Scope

Make the allowlisted AI knobs editable with save states and show setting history.

- [ ] Only editable values are editable.
- [ ] Validation and save errors are shown clearly.
- [ ] Successful writes refresh effective values and history.
- [ ] History is visible.
- [ ] Strings exist in both locales.

## Blocked by

- #772 - Allowlisted settings writes with history and audit
- #797 - Settings page shell and AI read section

## Read-list (in order)

1. The Settings AI section and the settings write and history APIs.

## Do NOT read

- docs/archive/
- Read-only secrets.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:unit:frontend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:frontend`
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- Read-only and secret values never become editable.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
