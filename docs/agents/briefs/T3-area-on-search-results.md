# Brief - T3 `area` on directory search results (backend)

**Ticket:** #325 · **Parent:** #319 · **Refreshed:** 2026-09-06
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Each `search_directory` directory entry carries the partner's `area` - derived from the partner's recorded service area exactly like `get_provider_profile` already does (service-area join with the Daltonganj fallback), never free-form. The public contract stays verified-safe: the search response gains `area` while remaining free of raw credential documents, emails, phones and PHI, enforced by a route-level disallowed-fields gate mirroring the provider-profile route. `directory.search` analytics and search semantics are unchanged.

Acceptance criteria (from #325):

- [ ] `DirectoryEntry` in the search response has an `area` field (string or null), populated from the partner's recorded service area with the existing Daltonganj fallback when none is recorded.
- [ ] The verified-safe gate for the public search route asserts `area` is present and that `artifact_refs`, `artifact`, `email`, `phone`, `identity_id`, practice address, and revocation fields never serialize - mirroring the existing provider-profile disallowed-fields test.
- [ ] Backend search tests assert the area value maps correctly (recorded area, null/missing area fallback), nearest-first ordering unaffected.
- [ ] `npm run test:unit:backend`, `npm run test:integration`, `npm run typecheck`, `npm run lint` pass.

## Read-list (in order)

1. `docs/architecture/internal-modules.md` MOD-002 spec - `DirectoryEntry` shape, service-area handling, directory-entry glossary (~1K)
2. The facade: the `DirectoryEntry` view model and the `search_directory` query path (the join structure and where a service-area join slots in; the current field list with distance + ordering) (~1.5K)
3. The facade `get_provider_profile` method - the EXISTING area-derivation seam to copy: `partner_service_areas.c.name` outerjoin + `DEFAULT_SERVICE_AREA_NAME` fallback, keeping entry + profile area derivation on one seam (~0.8K)
4. The `partner_service_areas` model + `DEFAULT_SERVICE_AREA_NAME` constant - the area source and fallback value (~0.4K)
5. The public directory search route (`/v1/directory/search`) - thin adapter, response model, no business logic (~0.3K)
6. `tests/integration/test_directory_search.py` - existing search/area assertions and fixtures to extend (~1.5K)
7. `tests/unit/test_provider_profile_route.py` disallowed-fields test - the verified-safe assertion pattern to mirror for the search route (~1K)

## Do NOT read

- Any frontend code (the client type gains `area` in ticket #327), other modules, the artifact store, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration` (skips when Postgres unreachable)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- Baseline truth (2026-09-06, before any edit): backend unit 1243 pass; integration 198 pass / **2 pre-existing failures unrelated to MOD-002** (`test_bootstrap_schemas.py`, `test_consent_check_gate.py::test_p95_latency_under_50ms`) - do not chase them.
- Mirror `get_provider_profile`'s area derivation verbatim (area_name outerjoin, `DEFAULT_SERVICE_AREA_NAME` fallback) - the shared seam keeps entry and profile areas consistent. Do NOT invent a new derivation.
- The facade comment "never invents an area string" guard on `DirectoryEntry` is retired as part of this change - the projection now carries area.
- `area` must be string|null - never a required string, and the verified-safe route test must prove no artifacts/emails/phones/identity fields leak on the search response (extend the provider-profile disallowed-fields pattern to the search route).
- Ticket #327 (frontend) waits on this; once area ships, the frontend shape guard tolerates the extra field, so landing this first will not break the client.
