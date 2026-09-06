> **SUPERSEDED 2026-09-05** · #308 was split for session-size. This brief documents the union scope only. Implement via the sub-tickets:\n> - `PHASE-6-T02a-directory-search-core.md` (#313) - facade + route + event\n> - `PHASE-6-T02b-directory-search-cache.md` (#314) - Redis cache layer

# Brief - PHASE-6-T02 Public Directory Search API

**Ticket:** #308 · **Parent:** #306 · **Refreshed:** 2026-09-05 · **SUPERSEDED (see banner above)**
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Patients can search the public directory without logging in, filtering by partner type, specialty (doctors only), and free-text name match. Results sorted nearest-first by distance. Wider-area fallback when nothing matches nearby (relax location only, keep filters, label "outside your area"). Redis caching (optional, SQL fallback). `directory_search` analytics event fires per search.

Acceptance criteria (from ticket):

- `search_directory(query, filters, geo)` facade method in MOD-002 returns filtered, distance-sorted directory entries
- Filtering: partner_type (doctor/lab/chemist), specialty (doctors only, closed pick-list), free-text over partner name
- Distance sorting via SQL range on `practice_latitude`/`practice_longitude` (nearest-first)
- Wider-area fallback: relax location only, re-run nearest-first, present under "outside your area" label
- Unauthenticated public endpoint at `GET /v1/directory/search`
- Redis cache of search results (consent/redis_cache.py pattern), invalidated on `partner.activated` and `credential.invalidated`
- `directory_search` event registered in `bus/events.py` and `internal-modules.md` §4.2 (analytics, not regulated act)
- Integration tests: only `[Active]` + valid-credential partners appear, fallback fires correctly, nearest-first ordering

## Read-list (in order)

1. `CONTEXT.md` glossary Phase 6 section - verified, directory entry, wider-area fallback definitions; "verified" derived (never stored), tick-gone=card-gone rule. (~1.5K)
2. `internal-modules.md` §3.2 (MOD-002 spec) + §4.2 (event registry) - search semantics: gated to `[Active]`, filters select + distance orders, no blended relevance; p95 < 250ms cached; register `directory_search` in the outbound registry per the "register changes there" rule. (~2K)
3. `docs/adr/0011-credential-expiry-lazy-daily-sweep.md` and `docs/adr/0012-directory-entry-unit-per-partner.md` - lazy read-hide (the search filter derives validity from credential dates, never trusts cache) and one-entry-per-partner shape. (~2K)
4. `apps/backend/modules/partner/facade.py` - the `PartnerFacade` pattern: typed public methods writing envelopes into `partner_outbox` in the same transaction; read path methods return DTOs. Search is a read-only facade method over `directory_index` joined with `partner_profiles`/`partner_credentials`. Grep for an existing read method (e.g. `list_verification_queue`) to copy the shape; do not read the whole 1600-line file. (~2K)
5. `apps/backend/modules/partner/adapters/routes.py` - router/facade/error-handler pattern: typed Pydantic request/response, `request.app.state.partner_facade`, error envelope via `error_response(...)`. Public route has no auth dependency. (~1.5K)
6. `apps/backend/modules/consent/redis_cache.py` + `app/config.py` redis settings - the optional-with-SQL-fallback cache pattern to replicate for directory results. (~1K)
7. `apps/backend/bus/events.py` + `bus/envelope.py` + `scripts/check_event_names.py` - canonical event constants, `domain.action` regex (`^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$`), and the snake_case gate. `directory_search` is dot-notation and NOT a regulated act. (~1K)

## Do NOT read

- Frontend code, prototype files, IAM module, notify module, `docs/archive/`, other ADRs beyond 0011/0012.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASSED 2026-09-05
- `npm run test:unit:backend` - PASSED 2026-09-05 (1205 passed)

## Done-verify (acceptance criteria → commands)

- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run test:integration` (needs local Postgres; skips if unreachable - see `tests/integration/README.md`)

## Handoff notes

- PRD's `provider_selected`/`provider_selected` spellings are legacy snake_case and REJECTED by `check_event_names.py`; the valid name is `partner.selected` (dot-notation, `partner` domain is gated). Ticket #306 says `directory_search` for the analytics event - use exactly that.
- `directory_search` telemetry should record the fallback firing and the relaxed-run payload; actor id is nullable/cohort-tagged (anonymous patient, blueprint gap G2).
- Search reads must NOT trust Redis for correctness: a stale cache row for a deactivated partner must never surface because the read path re-derives the tick from activation + credential dates (ADR-0011 lazy correctness). The cache is an accelerator only.
- Ordering: filters select, distance orders. No relevance blending.
- Tests that assert external behavior only (which partners appear, fallback labeling, order) - not cache internals.
