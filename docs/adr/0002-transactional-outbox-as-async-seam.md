# ADR - 0002: Transactional outbox as the async seam

**Status:** accepted
**Date:** 2026 - 08 - 10
**Decides:** The asynchronous seam between modules - the at - least - once delivery contract for every event in the registry (`internal - modules.md` §4.2).
**Traceability:** `MOD - 001`…`MOD - 011`, `NFR - 001`, `coding - standards.md` §4, `PHASE - 1 - FOUNDATION` (issue #16).

## Context

Modules must communicate asynchronously, but `NFR - 001` (total monthly spend ≤ ₹2,000) forbids a managed broker, and the module isolation rule forbids cross - schema SQL. The seam has to be crash - safe: a state change and its event must not be separable by a process dying between them, and a crash mid - delivery must not lose events.

## Decision

1. **Per - module outbox tables, written in the same DB transaction as the state change.** Each module owns a `*_outbox` table; the event envelope carries `event_id`, `event_type`, `schema_version`, `occurred_at`, `producer`, and a typed `payload`.
2. **The dispatcher is pure transport.** An async worker polls the outboxes, durably claims rows `pending → inflight` via `UPDATE ... WHERE status='pending' RETURNING` before any handler runs, and fans events out in - process to subscribers registered per `event_type`. Stale `inflight` rows are reclaimed after a timeout. The dispatcher never authors events and never reads subscriber ledgers or domain tables.
3. **Delivery is at - least - once; subscribers are idempotent.** Each subscriber records `event_id` in its own `consumed_events` ledger (in its own schema) before applying effects, so a replay is a no - op. Success = the handler returned without exception.
4. **Delete on success, retry, then dead - letter.** An outbox row is deleted once every subscriber handled it (no tombstone - the subscriber ledger is the delivery record). Per - subscriber failure returns the row to `pending` with exponential backoff, capped at 5 attempts, then `dead_letter` status and an alert.
5. **Audit events flow the same way.** `audit.event` is published by the owning module into its own outbox in the same transaction and consumed by MOD - 011, which appends to the `audit` schema. The dispatcher does not synthesize them.

## Considered options

- **Managed broker (Kafka/SQS):** rejected - violates the `NFR - 001` cost floor.
- **Fan - out at publish time:** rejected - breaks the atomicity of state change + event.
- **Tombstoning outbox rows:** rejected - the subscriber ledger already records delivery; tombstones would grow tables for no benefit.
- **Shared dedupe ledger:** rejected - it would require every subscriber to write across a schema boundary, violating the module isolation rule.

## Consequences

- Every module ships an outbox writer and a `consumed_events` ledger; every consumer has an idempotency test (replay of the same `event_id`).
- The async seam is proven by the `round - trip` test before any business event exists (Phase 1).
- Sync cross - module calls remain possible only via `facade.py`; async is this outbox fan - out. There is no third cross - module channel.
