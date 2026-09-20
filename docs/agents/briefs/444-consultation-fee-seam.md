# Brief - 444 BE: consultation fee seam

**Ticket:** #444 · **Parent:** #438 · **Refreshed:** 2026-09-16
**Reading surface:** ~2.5K tokens (budget 10K) - within budget

## Scope

A nullable consultation fee on the partner profile, exposed on the directory entry and the verified-safe provider profile projection, and settable by the doctor through a partner-scoped update endpoint. Until set, the fee is null and never blocks a pick - it is not PHI and needs no credential gate.

AC:

- [ ] Directory entry and provider profile projection expose a nullable consultation fee
- [ ] A doctor can update their own consultation fee; other actors are rejected
- [ ] An unset fee stays null and never gates the pick (no fee required to proceed)
- [ ] Route tests cover the projection exposure and the doctor-only update

## Read-list (in order)

1. `modules/partner/directory_facade.py` `search_directory`, `get_provider_profile`, `record_partner_selected` - the projections that must surface the fee (~600 tokens)
2. `modules/partner/directory_models.py` `DirectoryEntry`, `DirectorySearchView`, `ProviderProfileView` - the read-side shapes to extend (~400 tokens)
3. `modules/partner/adapters/routes.py` partner router + partner-scoped update pattern and the `require_partner`/doctor guard - home of the new update endpoint (~400 tokens)
4. `tests/unit/test_directory_search_route.py`, `test_provider_profile_route.py` - the route-test seam A pattern (~800 tokens)
5. `CONTEXT.md` directory entry / verified / specialty glossary + Issue #438 "backend delta 6" and user story 10 (~350 tokens)

## Do NOT read

- Care/intake/consent modules, frontend, `docs/archive/`, blueprint/PRD beyond the #438 excerpt.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - expect only the 3 known pre-existing dev-OTP env failures in `test_app_shell.py`/`test_seed_demo.py`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new tests: fee present on both projections (index + profile), doctor-owned update succeeds, non-doctors rejected with the correct envelope code, unset fee stays null.

## Handoff notes

- The fee is a partner-profile field, not a credential; keep the verified-safe posture - no credential-gate check on the fee.
- The frontend renders "fee not set" in #449/#450; the backend contract is simply null-if-unset, do not add pick gating.
