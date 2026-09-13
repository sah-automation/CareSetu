# Brief - 333 Partner facade coordinator prefactor (WI-2 prefactor)

**Ticket:** #333 · **Parent:** #330 · **Refreshed:** 2026-09-06
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Turn the single large partner facade into a thin coordinator, following the ADR-0006 IAM precedent. This prefactor establishes the coordinator shape and centralizes shared infrastructure so the four sub-facade tickets can land cleanly. It does NOT move lifecycle methods into sub-facades yet.

The coordinator keeps the exact same public interface (method names, signatures, result models) so routing code and cross-module callers need zero edits. It becomes a thin composition root that constructs and exposes shared dependencies: engine, credential-validity deep module (from WI-1), artifact store, directory-cache seam. Internal duplication collapses once: shared profile-load helper, shared registration race-retry helper, and result models centralized so each future sub-facade owns its own models.

Acceptance criteria (from ticket):

- Identical public facade interface after the prefactor.
- Shared profile-loading and race-retry helpers exist; repeated blocks delegate to them.
- Coordinator constructs and shares engine, deep module, artifact store, directory-cache seam.
- Each sub-facade owns its result models (no shared model file mixing concerns).
- Existing partner/iam integration and route suites pass unchanged.
- Backend unit + integration suites, mypy strict typecheck, lint, migration single-head gate all green.

## Read-list (in order)

1. `docs/adr/0006-iam-facade-split.md` - the facade-split seam pattern to replicate (~1.5K tokens)
2. `apps/backend/modules/partner/facade.py` 156-479 - all result models; identify which grouping belongs to which lifecycle seam (~3.0K tokens)
3. `apps/backend/modules/partner/facade.py` 856-910 - `PartnerFacade.__init__` plus constructor-shared dependencies (engine, artifact store, iam facade, audit facade, directory-cache) (~0.8K tokens)
4. `apps/backend/modules/partner/facade.py` 590-639 - `_load_profile` / `_load_profile_by_identity` (the repeated profile-load pattern) (~0.6K tokens)
5. `apps/backend/modules/partner/facade.py` 671-719 - `_insert_registered_profile` and the registration race-retry block to collapse (~0.7K tokens)
6. `apps/backend/modules/partner/facade.py` - method inventory grouped by lifecycle seam: registration (register 911, register_partner 987, resolve_partner 1030, resolve_partner_id_by_identity 1049, get_my_status 1064), credential intake (get_my_verification 1086, submit_credentials 1173, get_rejection_reason 1311, appeal 1350), operator gate (operator_decision 1388, grace_lapse 1507, list_verification_queue 1744, get_verification_detail 2193), directory (search_directory 1822, record_partner_selected 1981, get_provider_profile 2013) (~1.5K tokens total scan)
7. Prior art: `tests/unit/test_mfa_facade.py` - the direct-seam test pattern the sub-facades will mirror (~0.6K tokens)

## Do NOT read

- The facade's close-out/eligibility internals in detail (`invalidate_credential`, `close_out_expired_credentials`, `purge_expired_credentials`, predicates) - owned by WI-1 / directory ticket.
- IAM internals, frontend, archives.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (1258 passed)
- `npm run typecheck`
- `npm run migration-check`

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (unchanged suite passes)
- `npm run test:integration`
- `npm run typecheck` (clean)
- `npm run lint`
- `npm run migration-check`

## Handoff notes

- Blocked by #331 (credential-validity deep module). Feed-forward from #331: the module's close-out transition and predicates are the deep module instance the coordinator will construct and share.
- This prefactor must keep the coordinator public interface byte-identical. Do not rename or reorder methods; changes land in the sub-facade tickets.
- Follow the IAM precedent exactly: coordinator thin ~50-150 line class, sub-facades own their models and re-export through the coordinator for backward compat.
- Test coverage at this stage is the unchanged existing suites - behavioral preservation is the oracle.
- After this prefactor, the four sub-facade tickets (#332 registration, #338 credential-intake, #334 operator-gate, #337 directory) each move their method groups behind the coordinator.
