# Brief - 703 B4b - Remaining event subscriptions -> business rollup + audit-tamper alerts

**Ticket:** #703 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~9.5K tokens (budget 10K) - within budget

## Scope

Extend MOD-013's consumer to the rest of its subscriptions: `case.*`, `partner.*`, `consent.*`, `record.accessed`, and `audit.*` (including `audit.tamper_detected`). Accumulate the registry-driven business counts into `obs_business_daily` (`metric_key`, `date`, `value` JSON), and turn `audit.tamper_detected` (and the existing AI-egress guardrail signal, if present as an event) into an alert row in `obs_alert_events` with severity, kind, title, and a PHI-free JSON payload. Reuse the same idempotency ledger so replays are no-ops. Do not rebuild the tamper guard or the egress guardrail - surface them.

### Acceptance criteria

- [ ] Handlers registered for the `case.*`, `partner.*`, `consent.*`, `record.accessed`, and `audit.*` families through the existing registry; each writes its ledger row first.
- [ ] Business counts land in `obs_business_daily` keyed by `metric_key` + `date`.
- [ ] `audit.tamper_detected` produces an `obs_alert_events` row; the payload is PHI-free.
- [ ] Every subscription is replay-safe (one ledger row, no double effect).
- [ ] `npm run typecheck`; `npm run test:unit:backend` pass.

Blocked by #692 child B4a (consumer scaffold + ledger + AI usage aggregates).

## Read-list (in order)

1. The B4a consumer scaffold and B3 schema models (`obs_business_daily`, `obs_alert_events`, `obs_consumed_events`) - the registry-driven accumulation, ledger seam, and payload tables to extend; both are sibling tickets, so conform to the interfaces they name. (~2.5K)
2. `bus/events.py` `EVENT_*` constants + `REGULATED_ACT_TYPES` - the canonical `case.*` `partner.*` `consent.*` `record.accessed` `audit.*` `ai_egress.recorded` family names; never author new literals. (~1.5K)
3. `modules/audit/adapters/__init__.py` `register_handlers` + `log_tamper_detected` - the canonical registration, payload-mirror, and ledger-first `run_handler` handler shape to copy. (~2.5K)
4. `bus/handler_harness.py` `run_handler` - the contract every handler delegates to: consume-payload re-validation, ledger row first, effect second, one transaction. (~0.8K)
5. `modules/audit/domain/consumer.py` `TamperDetectedPayload` - the tamper payload shape to mirror into a PHI-free `obs_alert_events` payload. (~0.8K)
6. `bus/registry.py` `HandlerRegistry.register` / `register_payload_model` - the one-model-per-event-type-repo-wide rule that decides when MOD-013 registers a mirror vs relies on another module's model. (~0.5K)
7. `tests/integration/test_audit_round_trip.py` - the replay/idempotency test shape (publish → dispatch → replay same `event_id` → one row). (~1K)

## Do NOT read

- Anything outside the read-list (frontend, migrations, the B5a rollup engine, the nightly workflow, other modules' internals).
- The tamper guard trigger / AI-egress guardrail implementations - they are surfaced, not rebuilt.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS (measured 2026-10-12).
- `npm run test:unit:backend` - PASS (2925 passed, measured 2026-10-12).

## Done-verify (acceptance criteria → commands)

- `npm run typecheck` - PASS.
- `npm run test:unit:backend` - PASS, including a new consumer test asserting: tamper -> one `obs_alert_events` row with a PHI-free payload; business-daily rows keyed by `metric_key` + `date`; replay of the same `event_id` is a no-op (one ledger row, no double effect).
- `npm run test:integration` - run if a local native Postgres is reachable (skips otherwise); assert the consumer path end to end.

## Handoff notes

- Copy the audit module's consumer shape exactly (`modules/audit/adapters/__init__.py`): `register_handlers(registry)` registers handlers + payload mirrors; each handler builds a local `_impl(connection, payload)` and calls `run_handler(envelope, MirrorPayload, _impl, name, OBSERVABILITY_SCHEMA)`.
- Event-type ownership: `partner.activated` / `partner.rejected` / `credential.invalidated` payload models are owned by other modules and must NOT be re-registered; `run_handler` re-validates into MOD-013's own mirror. Register a mirror only for events no module has claimed.
- Ledger semantics are the idempotent-subscriber rule (CONTEXT.md glossary, ADR-0002 §3): the `consumed_events` row and the effect roll back together, so a crash retries cleanly.
- `audit.tamper_detected` is telemetry, not a regulated act (`REGULATED_ACT_TYPES` excludes it); the guardrail signal (`ai_egress.recorded`) is likewise surfaced, never re-derived.
- Alert payload must carry severity/kind/title + a no-PHI JSON payload (`error-handling-observability.md` §4-§5); ids/facts only, never transcript, phone, or raw provider payloads.
- Single private schema per module (coding-standards §2): all writes stay in MOD-013's `observability` schema; the B3 migration registered it as the 12th `MODULE_SCHEMAS` entry.
