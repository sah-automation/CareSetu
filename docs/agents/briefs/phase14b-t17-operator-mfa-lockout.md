# Brief - #778 Operator TOTP failure counter and lockout

**Ticket:** #778 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~7K

## Scope

Persist operator TOTP verification failures in a separate committed transaction. At the configured threshold the operator is locked for a configurable period. A successful verification resets the counter. Failures and lockouts emit events.

- [ ] Failures increment the persisted counter in a separate committed transaction.
- [ ] The configured threshold locks the operator for the configured period.
- [ ] A successful verification resets the counter.
- [ ] Locked operators cannot complete login.
- [ ] Failures and lockouts emit events for security signals.

## Blocked by

- #763 - IAM operator profile schema and admin backfill

## Read-list (in order)

1. Spec #761, operator MFA lockout decisions.
2. The operator login session facade and MFA verification.
3. The existing phone OTP lockout pattern.
4. The operator profile model.

## Do NOT read

- docs/archive/
- Patient and partner lockout behavior except as prior art.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`

## Handoff notes

- Do not change patient or partner lockout semantics.
- The counter commit must survive the failed login transaction.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
