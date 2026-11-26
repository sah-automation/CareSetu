# Brief - PHASE-6-T02a Directory Search Core (Facade + Route + Event)

**Ticket:** #313 · **Parent:** #306 (split from #308) · **Refreshed:** 2026-09-05
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Patients can search the public directory without logging in, filtering by partner type (doctor/lab/chemist), specialty (doctors only, closed pick-list), and free-text over partner name. Results are sorted nearest-first by distance. When nothing matches nearby, the search widens the area (keeping filters) and labels results "outside your area". Redis caching is deliberately out of scope (T02b) - the facade works SQL-fallback-only.

Acceptance criteria (from ticket):

- [ ] `search_directory(query, filters, geo)` facade method in MOD-002 returns filtered, distance-sorted directory entries
- [ ] Filtering: partner_type (doctor/lab/chemist), specialty (doctors only, from closed pick-list), free-text over partner name
- [ ] Distance sorting via SQL range on `practice_latitude`/`practice_longitude` (nearest-first)
- [ ] Wider-area fallback: relax location only, re-run nearest-first, present under "outside your area" label
- [ ] Lazy read-hide (ADR-0011): only `[Active]` partners with unexpired, unrevoked credentials, computed against recorded dates
- [ ] Unauthenticated public endpoint at `GET /v1/directory/search`
- [ ] `directory_search` event registered in `bus/events.py` and `internal-modules.md` §4.2 (analytics, not regulated act); fires once per search, recording the fallback flag
- [ ] Integration tests: only `[Active]` + valid-credential partners appear, wider-area fallback fires correctly, ordering is nearest-first

## Read-list (in order)

1. `CONTEXT.md` glossary Phase 6 section - directory entry, verified, wider-area fallback definitions; "verified" derived (never stored), tick-gone = card-gone rule. (~1K)
2. `internal-modules.md` §3.2 (MOD-002 search spec) + §4.2 (event registry) - filters select + distance orders (no relevance blending), p95 < 250ms cached, `directory_search` registered per the "register changes there" rule. (~1.5K)
3. `docs/adr/0011-credential-expiry-lazy-daily-sweep.md` + `docs/adr/0012-directory-entry-unit-per-partner.md` - lazy read-hide (search derives validity from credential dates, never trusts cache) and one-entry-per-partner shape. (~2K)
4. `apps/backend/modules/partner/facade.py` - grep `list_verification_queue` for the filtered/sorted read + DTO shape to copy; do NOT read the whole ~1600-line file. (~1.5K)
5. `apps/backend/modules/partner/adapters/routes.py` - router/facade/error-handler pattern; the search route is a NEW public `/v1/directory` router with no auth dependency. (~1K)
6. `apps/backend/bus/events.py` + `bus/envelope.py` + `scripts/check_event_names.py` - canonical constants, `domain.action` regex, snake_case gate. `directory_search` is dot-notation, NOT a regulated act. (~1K)

## Do NOT read

- Everything Redis/consent related (cache is T02b), frontend code, prototype files, IAM module, notify module, `docs/archive/`, ADRs beyond 0011/0012.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASSED 2026-09-05 (mypy strict 183 files, tsc clean)
- `npm run test:unit:backend` - PASSED 2026-09-05 (1211 passed)

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run test:integration` (needs local Postgres; skips if unreachable - see `tests/integration/README.md`)

## Handoff notes

- PRD's `provider_selected` spellings are legacy snake_case and REJECTED by `check_event_names.py`; parent #306 mandates `directory_search` for the analytics event - use exactly that.
- `directory_search` telemetry records the fallback firing and the relaxed-run payload; actor id is nullable/cohort-tagged (anonymous patient, blueprint gap G2).
- Ordering: filters select, distance orders. No relevance blending.
- Search must NOT trust any cache for correctness (ADR-0011 lazy correctness) - build the read path as if no cache exists; T02b wraps it later.
- The `partner_directory_index` table, its `is_active` column, and the `ix_partner_directory_index_type_active` index already exist (from #307) - query it directly; no schema work here.
- Tests assert external behavior only (which partners appear, fallback labeling, order), not internals.
- Blocked by #307 (directory schema) - starts once #307 closes.
