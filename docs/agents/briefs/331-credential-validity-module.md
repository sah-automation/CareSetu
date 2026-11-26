# Brief - 331 Credential-validity deep module (WI-1)

**Ticket:** #331 · **Parent:** #330 · **Refreshed:** 2026-09-06
**Reading surface:** ~9.5K tokens (budget 10K) - within budget

## Scope

Concentrate the partner directory-eligibility concept into one module-level deep module inside the partner module. The module owns: the read-side SQL eligibility predicates (has any credential, has invalid credential, is directory-visible); a pure eligibility decision over credential rows (unit-testable without SQL); and the single close-out transition that per invalidated credential writes `credential.invalidated`, removes the directory entry, and performs the best-effort cache flush.

The four close-out paths converge on this transition: operator reject of an active partner, credential revocation, credential expiry close-out, credential purge. ADR-0011 semantics absorbed unchanged (lazy read-hide, daily sweep contract). `search_directory`, `get_provider_profile`, and cached-visibility re-derivation read eligibility from the new module.

Acceptance criteria (from ticket):

- New module-level deep module owns eligibility predicates, pure decision, close-out transition.
- Pure decision unit-tested from credential rows without a database (mirrors partner state-machine pure-domain suite).
- All four close-out paths route through the single close-out transition.
- Convergent close-out integration test pins an indistinguishable `credential.invalidated` outcome across all paths.
- Search/profile/cached re-derivation read eligibility from the module.
- Existing partner/iam integration and route suites pass unchanged.
- Backend unit + integration suites, mypy strict typecheck, lint, migration single-head gate all green.

## Read-list (in order)

1. `docs/adr/0011-credential-expiry-lazy-daily-sweep.md` - the expiry semantics this module absorbs (~0.6K tokens)
2. `apps/backend/modules/partner/facade.py` 504-562 - eligibility predicates `_has_any_credential`, `_has_invalid_credential`, `_provider_visible` (~0.8K tokens)
3. `apps/backend/modules/partner/facade.py` 1388-1505 - operator reject branch of `operator_decision` (close-out path 1) (~1.6K tokens)
4. `apps/backend/modules/partner/facade.py` 1570-1643 - `invalidate_credential` (close-out path 2) (~0.9K tokens)
5. `apps/backend/modules/partner/facade.py` 1645-1742 - `close_out_expired_credentials` (close-out path 3) (~1.3K tokens)
6. `apps/backend/modules/partner/facade.py` 2314-2388 - `purge_expired_credentials` (close-out path 4) (~1.0K tokens)
7. `apps/backend/modules/partner/domain/events.py` - `credential_invalidated` envelope and `CredentialInvalidatedPayload` shape (~0.5K tokens)
8. `apps/backend/modules/partner/domain/credentials.py` - credential state and `credential.invalidated` reason vocabulary (~0.5K tokens)
9. `apps/backend/modules/partner/directory_cache.py` 185-230 - `invalidate_directory_cache`, `directory_visibility_changed` flush funnel (~0.5K tokens)
10. Prior art: `tests/unit/test_partner_state_machine.py`, `tests/integration/test_partner_credential_revocation.py`, `test_partner_credential_expiry_sweep.py`, `test_partner_credential_cleanup.py` - pure-domain + per-path close-out patterns to converge (~1.8K tokens)

## Do NOT read

- Partner facade registration/intake/queue methods (only the four close-out paths above).
- IAM internals, OTP, frontend, archives.
- `docs/archive/` - the PRD supersedes it.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (1258 passed)
- `npm run typecheck`
- `npm run migration-check` (single head OK)

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (all prior + new eligibility unit + convergent close-out test pass)
- `npm run test:integration`
- `npm run typecheck` (clean)
- `npm run lint` (pre-commit gate)
- `npm run migration-check`

## Handoff notes

- This is the root of the chain: no blockers. It feeds #333 (coordinator), which feeds all sub-facade tickets.
- The eligibility predicates and close-out orchestration currently live in a single `PartnerFacade` (class at `facade.py:856`). The module must be created inside the partner module and leave the facade's public interface intact.
- The close-out transition must fire one `credential.invalidated` event per invalidated credential, deindex the directory, and best-effort flush the directory cache - identical across all four paths.
- ADR-0011's lazy read-hide means reads must keep working while an expired credential hasn't been swept; the pure decision must reflect "expired counts as not-valid" even before sweep.
- `reason` vocabulary comes from `domain/credentials.py`; do not invent new reasons.
