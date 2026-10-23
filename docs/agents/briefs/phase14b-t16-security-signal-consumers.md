# Brief - #777 Security signal aggregation consumers

**Ticket:** #777 - **Parent:** #761 - **Published:** 2026-10-23
**Reading surface:** ~9K

## Scope

Consume existing events into minute-granular security signals for auth failures, OTP failures and lockouts, operator MFA failures and lockouts, record denials, consent revocations, and rate-limit responses. Subject keys are hashed or empty and no phone number or free text is stored.

- [ ] Each producer event increments the correct signal kind per minute.
- [ ] Subject keys are hashed or empty.
- [ ] No phone number, OTP value, or free text is stored.
- [ ] Consumers are idempotent and replaying an event is a no-op.
- [ ] Tests cover each producer and the mirror filtering.

## Blocked by

- #765 - Observability security signal, CSP aggregate, and alert delivery schema

## Read-list (in order)

1. Spec #761, security signal decisions.
2. The observability consumer and ledger pattern.
3. The event registry for IAM, consent, care, and gateway events.
4. The pseudonymous hashing scheme.

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

- Never scan raw events.
- CSP and prompt-injection signals land in their own tickets.
- Do not add a generic event mirror.
- Read only the named sections and grep for interfaces by name. Do not read whole files, unrelated modules, or generated files.
