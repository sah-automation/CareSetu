# Brief - PHASE-6-T03 Provider Profile API

**Ticket:** #309 · **Parent:** #306 · **Refreshed:** 2026-09-05
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Patients can open a provider's public profile showing verified credentials (type + status labels, not raw documents) and a "verified" indicator. Payload contains only verified-safe fields - never raw credential documents, emails, phones, or PHI.

Acceptance criteria (from ticket):

- `get_provider_profile(partner_id)` facade method returns verified-safe fields only
- Profile payload: name, partner_type, specialty (doctors), area, verified indicator, credential type + status labels
- `verified` derived from `[Active]` status AND all credentials unexpired AND unrevoked (never stored)
- Public unauthenticated endpoint at `GET /v1/directory/providers/{id}`
- Partner not in `[Active]` state or with no directory_index entry returns 404
- Tests: safe fields only, expired/revoked partner 404s, verified indicator agrees with search visibility

## Read-list (in order)

1. `CONTEXT.md` glossary Phase 6 section - provider (display-only word, legal in public profile route name), verified derivation. (~1.5K)
2. `internal-modules.md` §3.2 (MOD-002 spec) - `get_provider_profile(partner)` in sync APIs; profile view p95 < 200ms; traceability FEAT-005 → `partner_profiles`, `partner_credentials`. (~1K)
3. `docs/adr/0012-directory-entry-unit-per-partner.md` - profile keys on one `partner_id`, one geo point; multi-location deferred. (~1K)
4. `apps/backend/modules/partner/facade.py` - facade read-method pattern (grep `list_verification_queue` or `get_my_status` for a returning-a-DTO shape; do not read the whole file). The profile DTO is the contract for what the public route serializes. (~2K)
5. `apps/backend/modules/partner/adapters/routes.py` - route → facade → typed response pattern, no-auth public route, error envelope handler. (~1.5K)
6. `apps/backend/modules/partner/schema/models.py` - `partner_profiles`/`partner_credentials` columns so the DTO maps only safe fields. (~1K)

## Do NOT read

- Frontend code, Redis/consent module, IAM module, notify module, prototype files, `docs/archive/`, ADRs beyond 0011/0012.
- Do NOT build credential-document exposure; the credential artifacts live encrypted in object storage and never leave it for this endpoint.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASSED 2026-09-05
- `npm run test:unit:backend` - PASSED 2026-09-05 (1205 passed)

## Done-verify (acceptance criteria → commands)

- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run test:integration` (needs local Postgres; skips if unreachable)

## Handoff notes

- "Verified" is never a stored column - derive from partner status + credential dates at read time; this ticket's indicator must use the same derivation as T02's search so tick-gone = card-gone.
- The public profile route name `providers/...` is the one place `provider` (display word) is legal; `partner` is the domain word everywhere in schema/model/events.
- A 404 (not a "hidden" 200) for non-`[Active]` / no-index partners matches the privacy posture; verify against how the frontline renders the not-found state (T06).
- Integration test pattern: `tests/integration/` live-Postgres tests with alembic upgrade/downgrade fixtures.
