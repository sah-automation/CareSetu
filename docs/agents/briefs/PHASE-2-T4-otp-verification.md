# Brief - PHASE-2 T4 OTP verification + challenge machine

**Ticket:** #55 · **Parent:** #51 · **Refreshed:** 2026-08-12
**Reading surface:** ~4K tokens (execution budget 120K incl. initial read + tests) - within budget

## Scope

`verify_otp(phone, otp)`: correct code consumes the challenge (single-use), transitions identity `[Unverified] -> [Active]`, grants the patient role, and emits `patient.verified`. Wrong guesses decrement a 5-attempt budget without killing the code; a spent budget and expired (5-min TTL) or already-used challenges reject with a "request a new code" outcome; failures emit `patient.auth_failed`. No resend/lockout here - that is T5.

Acceptance criteria:

- [ ] Correct code: challenge consumed (single-use), identity Active, patient role granted, `patient.verified` outbox row in the same transaction
- [ ] Used code cannot be replayed
- [ ] Wrong guess decrements the budget; budget 0 -> challenge spent ("request a new code")
- [ ] Expired (5-min TTL) and spent challenges rejected
- [ ] Failures emit `patient.auth_failed`; success does not
- [ ] Endpoint wired through the gateway; unit tests cover success, wrong guess, replay, expiry, spent

## Read-list (in order)

1. #51 Implementation Decisions §2.4 + §2.6 - the challenge contract and events (~2K).
2. `docs/architecture/internal-modules.md` §3.1 MOD-001 - identity + OTP state machines (~1K).
3. The facade, exceptions, and outbox writer patterns from T3 (already in module) (~0.5K).
4. `docs/standards/security-phii-standards.md` - hashing at rest, no-PHI logging (~0.5K).
5. The mock SMS contract from T2 for reading the sent code in tests.

## Do NOT read

- Frontend, dispatcher internals, `docs/archive/`, `phase0/`, resend/lockout (T5), session logic (T6/T7).

## Baseline verify

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck:backend`

## Done-verify

- `npm run test:unit:backend` (verify machine tests)
- `npm run test:integration` (`patient.verified` / `patient.auth_failed` outbox rows)
- `npm run typecheck:backend`
- `npm run lint`

## Handoff notes

- Role grant for the patient lands here on verification (identity Active), feeding the scope claim later.
- The 5-attempt budget is per challenge, reset on issuance; wrong guesses never kill the code until budget 0.
- Prototype reference behavior: `otpState.ts` `submitOtp` (MOCK_OTP contract, attempts-left, `expiredOrUsed`).
