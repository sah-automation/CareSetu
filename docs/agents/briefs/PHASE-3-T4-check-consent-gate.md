# Brief - T4 check_consent fail-closed gate with cache

**Ticket:** #213 · **Parent:** #209 PHASE-3 · **Refreshed:** 2026-08-24
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

One stable, pure, fail-closed gate every future sharing path calls: counterparty identity + requested scope in; `allowed, consent_id, version, effective_scope` out - nothing more. No side effects, no egress writing (callers disclose, then record egress separately). Redis cache keyed patient+scope+counterparty keeps it invisible (p95 < 50 ms), invalidated on grant/revoke; SQL fallback must pass the same behavioral suite standing alone. Fail closed on cache miss, DB error, unknown state. `full_record` subsumes every specific scope when matching. Also captures the ratified ADR: standing grants + fail-closed gate.

Acceptance criteria: see #213 body verbatim.

## Read-list (in order)

1. Internal-modules MOD-004 spec - the check_consent contract section (signature fields, fail-closed rules, no capability tokens) (~1K)
2. Roadmap PHASE-3 testing decisions - latency + fault-injection rows define done (~1K)
3. The consent module as T3 landed it - consents table shape, status/version columns, facade construction pattern (diff of blocker, ~1.5K)
4. IAM facade dependency-wiring prior art (constructor injection style, app.state resolution) (~1K)
5. `docs/standards/error-handling-observability.md` - fail-closed error taxonomy, no-PHI logging (~0.7K)
6. An existing ADR (e.g. ADR-0002) as format reference for the new ADR (~1K)

## Do NOT read

- MOD-003 internals; AI-engineering flows (they consume this only Phase 7); Redis general docs beyond what the client library needs; `docs/archive/`.

## Baseline verify (must pass before the first edit)

Recorded green on 2026-08-24: lint; typecheck; backend units 654 passed.

For this ticket: `npm run lint`, `npm run typecheck`, `npm run test:unit:backend`, `npm run test:integration`.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` (pure-domain scope-subsumption + transition suites)
- `npm run test:integration` (invalidation immediacy, SQL-fallback-alone suite, fault-injection deny, p95 < 50 ms check all green)

## Handoff notes

- No Redis client exists anywhere in the backend yet - this ticket introduces the dependency + settings/env wiring + client lifecycle alongside the cache logic; keep the SQL fallback runnable with Redis absent so local/integration tiers stay simple.
- Signature returns FOUR fields (extends the documented three) so receipts can cite id+version - do not drop back to three.
- Cache invalidation hooks fire from T3's grant/revoke paths - coordinate by consuming the same facade seams, not by cross-module imports.
- The ADR should record: standing-grant model, fail-closed rule, four-field signature, cache keying + invalidation contract, and that this hot-path contract binds Phases 7-9.
