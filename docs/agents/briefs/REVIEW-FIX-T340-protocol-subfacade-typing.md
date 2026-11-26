# Brief - 340 Review fix: deduplicate PARTNER_SCHEMA and type sub-facade constructors (S2, S3)

**Ticket:** #340 · **Parent:** #339 · **Refreshed:** 2026-09-07
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Two coding-standard violations in the partner module from the #330 deepening:

1. **S2 single-source-of-truth:** `PARTNER_SCHEMA = "partner"` is re-defined locally in `credential_validity.py:50` while the canonical definition lives in `shared.py:41`.
2. **S3 no `Any`:** sub-facade constructors use `Any` or `ModuleType` for the `credential_validity` and `directory_cache` dependencies instead of concrete protocol types.

Fix both by defining two minimal `Protocol` classes in `shared.py` and replacing every `Any`/`ModuleType` constructor annotation with the matching protocol.

Acceptance criteria (from #340):

- [ ] `PARTNER_SCHEMA` defined in exactly one place (`shared.py`); `credential_validity.py` imports it from there.
- [ ] `CredentialValidityPort` protocol defined in `shared.py` (the 3 SQL predicates + `close_out_credentials`).
- [ ] `DirectoryCachePort` protocol defined in `shared.py` (3 async cache methods).
- [ ] `OperatorGateFacade` and `DirectoryFacade` use the protocols instead of `Any`.
- [ ] `RegistrationFacade` and `CredentialIntakeFacade` use `CredentialValidityPort` instead of `ModuleType`.
- [ ] `npm run typecheck`, `npm run test:unit:backend`, `npm run lint` pass.

## Read-list (in order)

1. `apps/backend/modules/partner/shared.py` - canonical `PARTNER_SCHEMA` (line 41) and the module to host the two protocols (~3K).
2. `apps/backend/modules/partner/credential_validity.py` - the duplicate constant (line 50), imports block, and the surface called through the protocol boundary: `provider_visible`, `has_any_credential`, `has_invalid_credential`, `close_out_credentials` (~2K).
3. `apps/backend/modules/partner/directory_cache.py` - the surface called through `DirectoryCachePort`: `get_cached_search`, `set_cached_search`, `directory_visibility_changed` (~1.5K).
4. `apps/backend/modules/partner/operator_gate_facade.py` - `__init__` (148-182), `Any` import (line 36), and how `credential_validity` / `directory_cache` are used.
5. `apps/backend/modules/partner/directory_facade.py` - `__init__` (108-138) and usage of the two dependencies.
6. `apps/backend/modules/partner/registration_facade.py` - `__init__` (59-75), `ModuleType` (line 33).
7. `apps/backend/modules/partner/credential_intake_facade.py` - `__init__` (159-189), `ModuleType` (line 38).
8. `docs/standards/coding-standards.md` - S2 (line 108), S3 (line 34).

## Do NOT read

- domain layer, schema layer, outbox, routes, tests, the IAM module, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run lint`

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck` (strict mypy validates the protocols and their implementers)
- `npm run test:unit:backend`
- `npm run lint`
- Grep `Any` in `apps/backend/modules/partner/*_facade.py` - no hits.
- Grep `PARTNER_SCHEMA =` across backend - exactly one hit, in `shared.py`.

## Handoff notes

- Keep `CredentialValidityPort` minimal - only the methods sub-facades actually call. Do NOT add methods from the `credential_validity` module that are not called through the protocol boundary.
- The coordinator (`facade.py`) already passes module-level references that satisfy these protocols implicitly via duck typing; no code change expected there.
- Define both protocols in `shared.py` next to where the dependencies are imported in `facade.py`, so the coordinator stays unchanged.
- Parent for all review-fix briefs is #339. Concept drawn from review finding F1/F2.
