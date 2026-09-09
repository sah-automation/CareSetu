# Brief - 338 Partner credential-intake sub-facade (WI-2 p1b)

**Ticket:** #338 · **Parent:** #330 · **Refreshed:** 2026-09-06
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Extract the partner credential-intake lifecycle into its own sub-facade behind the thin coordinator (from #333), following the ADR-0006 IAM precedent. The coordinator delegates to the sub-facade while exposing an unchanged public interface.

The credential-intake sub-facade owns `submit_credentials`, `get_my_verification`, `get_rejection_reason`, `appeal` and their result models (`CredentialSubmission`, `CredentialSubmissionResult`, `RejectionReasonView`, `PartnerVerificationStatusView`). It takes the engine and the credential-validity deep module (from WI-1) in its constructor; admission checks (prefilter gate, rejection + appeal + throttle) stay domain: `prefilter.py`, `rejection.py`. A developer changing intake behavior no longer reads registration, operator-gate, or directory concerns.

Acceptance criteria (from ticket):

- Credential-intake sub-facade exists owning the intake methods and their result models.
- The prefilter admission gate, rejection reasons, appeal, and resubmission throttle keep their current semantics (ADR-0008 gate unchanged).
- The coordinator delegates intake methods to the sub-facade and re-exports its result models (unchanged public interface; routes and cross-module callers unchanged).
- Sub-facade unit tests drive the sub-facade through a mocked engine (never importing private facade helpers or scripting exact SQL call order), mirroring the iam MFA facade direct-seam suite.
- Existing partner/iam integration and route suites pass unchanged.
- Full harness green: backend unit tests, integration tests, mypy strict typecheck, lint, migration single-head gate.

## Read-list (in order)

1. `docs/adr/0008-partner-verification-gate.md` - AMB-003 two-step verification gate being preserved (~0.3K tokens)
2. `apps/backend/modules/partner/facade.py` 1173-1309 - `submit_credentials` (prefilter + earnings gate + credential rows + throttle) (~2.2K tokens)
3. `apps/backend/modules/partner/facade.py` 1086-1133, 1311-1386 - `get_my_verification`, `get_rejection_reason`, `appeal` (~1.5K tokens)
4. `apps/backend/modules/partner/facade.py` 218-261, 372-389 - result models `CredentialSubmission`, `CredentialSubmissionResult`, `RejectionReasonView`, `PartnerVerificationStatusView` (~0.7K tokens)
5. `apps/backend/modules/partner/domain/prefilter.py` - the submission eligibility gate (whole file) (~1K tokens)
6. `apps/backend/modules/partner/domain/rejection.py` - rejection reasons + appeal semantics (whole file) (~0.8K tokens)
7. `apps/backend/modules/partner/facade.py` - coordinator shape left by #333 (thin delegation) (~0.3K tokens)
8. Prior art: `tests/unit/test_partner_prefilter.py`, `tests/unit/test_mfa_facade.py` - prefilter unit coverage + direct-seam pattern (~1.2K tokens)

## Do NOT read

- Registration, operator-gate, and directory facade methods (separate sub-facade tickets).
- Close-out/eligibility internals beyond the shared deep-module interface (WI-1).
- IAM internals, frontend, archives.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (1258 passed)
- `npm run typecheck`
- `npm run migration-check`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (all prior + new sub-facade direct-seam tests pass)
- `npm run test:integration`
- `npm run typecheck` (clean)
- `npm run lint`
- `npm run migration-check`

## Handoff notes

- Blocked by #333 (coordinator prefactor), which is blocked by #331.
- The intake path is where rejected partners re-submit and appeal; keep the appeal window and resubmission-throttle semantics byte-identical (PHASE-5 FIX-S14/S13 prior art).
- Prefilter gate (`domain/prefilter.py`) must not read the directory cache directly - visibility stays with the deep module.
- Re-export the sub-facade's result models through the coordinator for backward compat.
