# Brief - 334 Partner operator-gate sub-facade (WI-2 p2a)

**Ticket:** #334 · **Parent:** #330 · **Refreshed:** 2026-09-06
**Reading surface:** ~8.5K tokens (budget 10K) - within budget

## Scope

Extract the partner operator-gate lifecycle into its own sub-facade behind the thin coordinator (from #333), following the ADR-0006 IAM precedent. The coordinator delegates to the sub-facade while exposing an unchanged public interface. When an operator decision rejects an active partner, the sub-facade routes the close-out through the credential-validity deep module's (from WI-1) single close-out transition - it does not re-implement the choreography.

The operator-gate sub-facade owns `operator_decision`, `list_verification_queue`, `get_verification_detail`, `grace_lapse` and their result models (`PartnerQueueItem`, `PartnerQueue`, `CredentialDetail`, `VerificationRound`, `AuditEventDetail`, `PartnerVerificationDetail`). It takes the engine, the credential-validity deep module, and the repository/audit seams in its constructor. A developer changing operator behavior no longer reads registration, credential-intake, or directory concerns.

Acceptance criteria (from ticket):

- Operator-gate sub-facade exists owning the gate methods and their result models.
- The reject-of-an-active-partner path routes close-out through the credential-validity deep module's single close-out transition (from WI-1), not its own choreography.
- The coordinator delegates operator-gate methods to the sub-facade and re-exports its result models (unchanged public interface; routes and cross-module callers unchanged).
- Sub-facade unit tests drive the sub-facade through a mocked engine (never importing private facade helpers or scripting exact SQL call order), mirroring the iam MFA facade direct-seam suite.
- Existing partner/iam integration and route suites pass unchanged.
- Full harness green: backend unit tests, integration tests, mypy strict typecheck, lint, migration single-head gate.

## Read-list (in order)

1. `apps/backend/modules/partner/facade.py` 1388-1505 - `operator_decision` (decision + reject close-out path + audit) (~2.2K tokens)
2. `apps/backend/modules/partner/facade.py` 1744-1821 - `list_verification_queue` (queue read + filters) (~1.5K tokens)
3. `apps/backend/modules/partner/facade.py` 2193-2312 - `get_verification_detail` (audit-chain assembly skimmed - covered by the verification-queue integration suite) (~1.6K tokens)
4. `apps/backend/modules/partner/facade.py` 1507-1568 - `grace_lapse` (grace-window auto-lapse, deferred skim ~1.0K tokens)
5. `apps/backend/modules/partner/facade.py` 262-353 - result models `PartnerQueueItem`, `PartnerQueue`, `CredentialDetail`, `VerificationRound`, `AuditEventDetail`, `PartnerVerificationDetail` (~1.6K tokens)
6. Coordinator shape left by #333 + credential-validity deep-module close-out transition (from #331) - the single transition the reject path routes through (~0.8K tokens)
7. Prior art: `tests/integration/test_partner_verification_queue.py`, `tests/integration/test_partner_grace_window.py`, `tests/unit/test_mfa_facade.py` - gate coverage + direct-seam pattern (~1.2K tokens)

## Do NOT read

- Registration, credential-intake, and directory facade methods (separate sub-facade tickets).
- Close-out orchestration internals beyond the deep-module transition (WI-1 owns them).
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

- Slightly over before trimming; two skims applied (audit-chain assembly, grace_lapse detail) land ~8.5K within budget. The audit chain is pinned by the verification-queue integration suite; `grace_lapse` reuse the operator_decision state-transition helpers.
- Blocked by #333 (coordinator prefactor), which is blocked by #331.
- The reject-of-active path > close-out transition is the WI-1 convergence; do NOT re-implement the stamp/deindex/event/flush choreography in this sub-facade.
- Reworked graph note: WI-3 (#336) was formerly blocked by the WI-2 operator-gate+directory pair; it now blocks on #332 (registration) and #337 (directory) only.
- Re-export the sub-facade's result models through the coordinator for backward compat.
