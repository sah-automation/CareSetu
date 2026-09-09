# Brief - T4 Register `partner.selected` + public ingest route (backend)

**Ticket:** #326 · **Parent:** #319 · **Refreshed:** 2026-09-06
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Product owners gain the `partner.selected` pick event: registered under the repo dot-notation grammar (superseding the PRD's legacy `provider_selected`), with an anonymous/nullable actor envelope carrying pick-only facts and no PHI - client-initiated product analytics, not a regulated act. A thin public, rate-limited POST route (same gateway surface as the existing `/v1/directory/*` routes) lets the frontend initiate the event; a facade method writes the partner-outbox row. The event-catalog gate asserts acceptance under `partner.selected` and rejection under any other spelling.

Acceptance criteria (from #326):

- [ ] `partner.selected` is registered in the event constants registry (MOD-002 outbound) and survives `check_event_names.py`; legacy `provider_selected` spelling and its snake_case variants are rejected by the catalog gate.
- [ ] A `partner.selected` envelope exists in the partner domain events with an anonymous/nullable actor and pick-only facts (no PHI, no credential data).
- [ ] A public POST route + facade method records one `partner.selected` outbox row per request, reusing the directory router's gateway rate-limiting; the route carries no business logic.
- [ ] Unit tests assert the payload carries only pick facts with an anonymous actor; catalog test asserts registration + rejection under any other spelling.
- [ ] `npm run test:unit:backend`, `npm run test:integration`, `npm run typecheck`, `npm run lint` pass.

## Read-list (in order)

1. `docs/architecture/internal-modules.md` MOD-002 spec + event registry §4.2 - the outbound event list, dot-grammar, and the outbox-mediated vs client-initiated boundary (~1.5K)
2. `docs/roadmap/implementation-roadmap.md` Phase 6 section + event registrations - where a new MOD-002 event name is recorded in docs (register the addition here too) (~1K)
3. `docs/standards/api-standards.md` - public route conventions, shared error envelope, rate limiting, request/response typing for the new POST (~2K)
4. `bus/events.py` - the `EVENT_*` constants, the `REGULATED_ACT_TYPES` distinction (analytics vs regulated acts), and the `directory.search` comment showing the legacy-name decision pattern (~0.6K)
5. `scripts/check_event_names.py` - the grammar gate your new constant must survive (~0.4K)
6. `modules/partner/domain/events.py` - start from `DirectorySearchPayload` + `directory_search_envelope` (anonymous nullable actor, analytics) as the template for the new payload/envelope (~0.5K)
7. The facade outbox write seam - `write_outbox` (from `bus.outbox_writer`) inside an `async with self._engine.begin()` transaction, as `directory.search` is written in `search_directory`; add a facade method the route calls (~0.8K)
8. `modules/partner/adapters/routes.py` `directory_router` - the public `/v1/directory` router + rate-limit surface the new route joins (~0.5K)
9. `tests/unit/test_bus_event_catalog.py` + `tests/unit/test_partner_events.py` - the catalog + payload acceptance tests to extend (~1K)

## Do NOT read

- Any frontend code, auth/iam, consent/regulated-act closure internals, other modules, `docs/archive/`. The event is deliberately NOT a regulated act.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration` (skips when Postgres unreachable)
- `npm run lint` (the `check_event_names` pre-commit hook runs this gate)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- Baseline truth (2026-09-06, before any edit): backend unit 1243 pass; integration 198 pass / **2 pre-existing failures unrelated to MOD-002** (`test_bootstrap_schemas.py`, `test_consent_check_gate.py::test_p95_latency_under_50ms`) - do not chase them.
- The event name is exactly `partner.selected`; `provider_selected` (legacy PRD spelling) and any snake_case form must be REJECTED by the catalog gate - that rejection is itself an acceptance criterion.
- The envelope mirrors `directory_search_envelope`: anonymous/nullable actor, pick-only facts (partner id + a source marker), no PHI. Keep the constant out of `REGULATED_ACT_TYPES`.
- The new POST route rides the same public, unauthenticated-but-rate-limited directory router; keep the adapter thin (parse body -> facade method -> write outbox row); no business logic in the route.
- Document the new event in the MOD-002 event registry docs (roadmap/internal-modules §4.2) so the cross-reference matrices stay the source of truth.
- Ticket #328 (frontend emission) waits on this; it consumes the route + registered name.
