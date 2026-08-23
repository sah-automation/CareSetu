# Brief - REFAC-5 Verify full test suite passes

**Ticket:** #170 · **Parent:** ADR-0006 · **Refreshed:** 2026-08-19
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

Full verification that the IAM facade split is complete and correct. Run all test suites, typecheck, lint, and boundary checker. Confirm the coordinator is a thin delegation shell. No code changes expected - this is a verification-only ticket.

Acceptance criteria:

- All unit tests pass: `npm run test:unit:backend`
- All integration tests pass: `npm run test:integration`
- Typecheck clean: `npm run typecheck`
- Lint clean: `npm run lint`
- Boundary checker passes (part of lint)
- `IamFacade` in `facade.py` is ~50 lines or less
- `SessionFacade`, `OtpFacade`, `IdentityFacade` exist as separate files
- `domain/shared.py` exists with shared helpers
- `IamFacade` re-exports all result models for backward compatibility

## Read-list (in order)

1. `docs/adr/0006-iam-facade-split.md` - the ADR governing this refactoring (~1.5K tokens)
2. `modules/iam/facade.py` - verify it is a thin coordinator (~0.5K tokens)
3. `modules/iam/session_facade.py` - verify it exists (~0.1K tokens)
4. `modules/iam/otp_facade.py` - verify it exists (~0.1K tokens)
5. `modules/iam/identity_facade.py` - verify it exists (~0.1K tokens)
6. `modules/iam/domain/shared.py` - verify it exists (~0.1K tokens)

Total: ~2.4K tokens

## Do NOT read

- Any other modules, frontend, test source files (only run test commands)
- Domain logic files (verification only, not editing)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (654 passed)
- `npm run test:integration`
- `npm run typecheck`
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (all pass)
- `npm run test:integration` (all pass)
- `npm run typecheck` (clean)
- `npm run lint` (clean, boundary checker passes)
- `wc -l apps/backend/modules/iam/facade.py` (<=50 lines)
- `ls apps/backend/modules/iam/session_facade.py apps/backend/modules/iam/otp_facade.py apps/backend/modules/iam/identity_facade.py apps/backend/modules/iam/domain/shared.py` (all exist)

## Handoff notes

- All prior REFAC tickets (1-4) must be complete.
- This is a verification-only ticket. No code changes expected.
- If any test fails, diagnose and fix - but the fix should be minimal (import path, type mismatch, etc.).
- The integration tests require a running PostgreSQL. If unreachable, they skip cleanly - that is expected.
