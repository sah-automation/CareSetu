# Brief - T1 Auth event names & status literals: single source of truth

**Ticket:** #84 · **Parent:** #75 · **Refreshed:** 2026-08-13
**Reading surface:** ~1.5K tokens (budget ~10K) - within budget

## Scope

The auth event-name vocabulary stops being redefined locally and the iam facade stops hardcoding challenge/identity status strings that already have named constants. Pure hygiene with no behaviour change: the codebase keeps one canonical definition of each event type (defined once, imported by producers) and one vocabulary for challenge/identity states, so consumers match on a single stable vocabulary and a rename can never drift between producer and the bus catalog.

Acceptance criteria:

- [ ] The iam module imports `otp.failed` (and the other auth event types) from the shared bus event catalog instead of redefining any name locally
- [ ] The stale "reserved / no module emits it yet" note on `otp.failed` in the bus catalog is corrected (iam emits it on lockout)
- [ ] The iam facade writes challenge status `Pending` and identity status `Active` via the named constants from the challenge machine, not string literals
- [ ] Unit suite passes; no behaviour change

## Read-list (in order)

1. `bus.events` - the canonical event catalog constants module (`EVENT_*`), including its "defined once and imported by every producing module" contract in the module docstring; note the stale `# Reserved` comment on `EVENT_OTP_FAILED` (~0.2K).
2. `modules.iam.domain.events` - the auth event payloads module (`OtpEvents`): imports the shared names for `patient.*` and `otp.sent` but redefines `EVENT_OTP_FAILED = "otp.failed"` locally at module scope (~0.4K).
3. `modules.iam.facade` - the iam facade (`IamFacade`): the literal status writes `status="Pending"` on challenge insert (two sites) and `status="Active"` on the patient role grant and its role-grant lookups (~0.4K).
4. `modules.iam.domain.verify` - the challenge machine: the status constant vocabulary (`CHALLENGE_PENDING`, `CHALLENGE_VERIFIED`, `CHALLENGE_EXPIRED`, `CHALLENGE_FAILED`, `IDENTITY_ACTIVE`, `IDENTITY_SUSPENDED`) plus the module contract that it is the single source of truth for its states (~0.3K).
5. `docs/architecture/internal-modules.md` §4.2 - the Asynchronous Event Registry: confirms `otp.failed` is already registered as published by `MOD-001` (IAM), so the doc side already says iam emits it (~0.2K).

## Do NOT read

- Frontend, dispatcher internals, `docs/archive/`, other modules' domain logic, the outbox/dispatcher transport internals (unchanged by this ticket).

## Baseline verify

- `npm run test:unit:backend` - already verified green centrally: 494 passed on 2026-08-13.

## Done-verify

- `npm run test:unit:backend`
- `npm run lint`

## Handoff notes

- Parent #75 standards finding: "event-name single source of truth" - local redefinition and the stale catalog note are the concrete instances.
- `bus.events` is the code-side mirror of the §4.2 registry (per its docstring, the registry is the doc-side source of truth); the "reserved" note at the top of the file is contradicted by the registry row already listing `MOD-001` as publisher and by the facade emitting `otp.failed` on lockout via `otp_failed_envelope` in the domain events module.
- ADR-0004 §6 lists `otp.failed` among the auth events that flow through the outbox; ADR-0002 establishes the outbox as the async seam. No behaviour change is permitted - pure constant/import substitution.
