# Brief - 337 Partner directory sub-facade (WI-2 p2b)

**Ticket:** #337 · **Parent:** #330 · **Refreshed:** 2026-09-06
**Reading surface:** ~7.8K tokens (budget 10K) - within budget

## Scope

Extract the partner directory read lifecycle into its own sub-facade behind the thin coordinator (from #333), following the ADR-0006 IAM precedent. The coordinator delegates to the sub-facade while exposing an unchanged public interface.

The directory sub-facade owns the patient-facing read surface: `search_directory`, `get_provider_profile`, `record_partner_selected`, and the cached-search accelerator (cache read/write plus visibility re-derivation on hit). It takes the engine, the credential-validity deep module (from WI-1), and the directory-cache seam in its constructor and owns its result models (`DirectoryEntry`, `DirectorySearchView`, `ProviderCredential`, `ProviderProfileView`). The close-out family does NOT move here - `invalidate_credential`, `close_out_expired_credentials`, `purge_expired_credentials` remain thin deep-module delegations on the coordinator (already routed through the credential-validity module's single close-out transition by WI-1), so this ticket stays within the SIZING-GATE.

Acceptance criteria (from ticket):

- Directory sub-facade exists owning search, provider profile, partner-selected analytics, and the cached-search accelerator, and their result models.
- Search, profile, and cache-hit re-derivation read directory visibility from the credential-validity deep module (from WI-1).
- The coordinator delegates directory read methods to the sub-facade and re-exports its result models (unchanged public interface; routes and cross-module callers unchanged).
- The coordinator keeps the close-out wrappers as thin delegations to the credential-validity deep module; `close_out_expired_credentials` remains callable for the daily worker sweep.
- Sub-facade unit tests drive the sub-facade through a mocked engine (never importing private facade helpers or scripting exact SQL call order), mirroring the iam MFA facade direct-seam suite.
- Existing partner/iam integration and route suites pass unchanged.
- Full harness green: backend unit tests, integration tests, mypy strict typecheck, lint, migration single-head gate.

## Read-list (in order)

1. `docs/adr/0011-credential-expiry-lazy-daily-sweep.md` - read-hide semantics driving cached re-derivation (~0.3K tokens)
2. `docs/adr/0012-directory-entry-unit-per-partner.md` - directory entry cardinality contract (~0.2K tokens)
3. `apps/backend/modules/partner/facade.py` 1822-1980 - `search_directory`, `_conditions`, `_rows` (SQL read path) (~2.0K tokens)
4. `apps/backend/modules/partner/facade.py` 2013-2192 - `get_provider_profile`, `record_partner_selected`, `_cached_search_view`, `_cached_ids_still_valid` (read + cached-search + analytics) (~2.2K tokens)
5. `apps/backend/modules/partner/facade.py` 390-479 - result models `DirectoryEntry`, `DirectorySearchView`, `ProviderCredential`, `ProviderProfileView` (~1.0K tokens)
6. `apps/backend/modules/partner/directory_cache.py` 120-230 - `get_cached_search`, `set_cached_search`, `invalidate_directory_cache`, `directory_visibility_changed` (cache seam) (~1.2K tokens)
7. Coordinator shape left by #333 + credential-validity deep-module read-side predicates (from #331): `_has_any_credential`, `_has_invalid_credential`, `_provider_visible` - the visibility contract reads share (~0.6K tokens)
8. Prior art: `tests/unit/test_mfa_facade.py`, directory search/profile unit + integration suites - direct-seam pattern and behavior pins (~0.6K tokens)

## Do NOT read

- The close-out family internals (thin deep-module delegations on the coordinator; detailed close-out owned by WI-1).
- Registration, credential-intake, and operator-gate facade methods (separate sub-facade tickets).
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
- This sub-facade is the primary consumer of the deep-module read-side predicates; subscribe to the `directory_visibility_changed` / cache-flush seams exactly as today.
- The daily sweep close-out stays reachable through the coordinator (worker calls `facade.close_out_expired_credentials`) - keep the coordinator's public wrapper, no worker change here (that lands in WI-3 #336).
- WI-3 (#336) blocks on this ticket: the sweep wrapper's iam-freedom is decided here (it must not require iam).
- Re-export the sub-facade's result models through the coordinator for backward compat.
