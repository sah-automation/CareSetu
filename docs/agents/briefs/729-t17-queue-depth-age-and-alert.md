# Brief - #729 Queue depth and oldest age with a high queue-age alert

**Ticket:** #729 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Show how much work is queued and how old the oldest queued item is. Queue depth exists today as per-module outbox backlog; the addition is age, because age is the leading indicator and depth is the lagging one. Depth and age are derived from an event, never from a cross-schema read.

- [ ] The intake module emits an AI-job-queued event when work enters the pipeline.
- [ ] The observability consumer derives depth as enqueued minus completed minus failed, and age from the oldest unclosed enqueue timestamp.
- [ ] Per-queue backlog is broken out across every module outbox, so a stuck module is identifiable rather than averaged, alongside the dead-letter row count.
- [ ] A high queue-age alert fires, so a stall pages before a depth alert would have.
- [ ] A distinct-actors-active figure is derived from the consumer's own consumed-event ledger, and both the API field name and the UI label state that it is recent activity, not simultaneous concurrency.
- [ ] True concurrency is not approximated or stored in Postgres; the surface links out to the tracing backend's gauge instead.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 16 and 17; the queue and activity user stories; Out of Scope (true concurrency as a Postgres-resident gauge). (~1K)
2. The outbox table discovery helper sanctioned for cross-module health reads, and the per-queue backlog/dead-letter figures it already produces. (~0.8K)
3. The intake pipeline's entry point where work is enqueued, and what "enters the pipeline" means for the transcription and structuring legs. (~1K)
4. The observability consumer's handler registration and payload-mirror pattern for a new event type. (~0.9K)
5. The rollup's alert builders and threshold dataclass, for the high queue-age kind and where thresholds are declared. (~0.8K)
6. The consumed-event ledger: what it records and what a "distinct actors active" figure can honestly be derived from. (~0.5K)
7. The trace-context/gauge convention in the tracing setup for how the surface links out to a real concurrency gauge. (~0.5K)
8. The consumer and rollup round-trip integration tests - extend both. (~1.2K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The AI gateway implementations, the retry/backoff internals.
- The langfuse batch pull, the collector configuration, the Grafana assets.
- The care and partner modules.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- **Two different signals, two different names.** Depth (enqueued minus completed minus failed) is lagging; age (oldest unclosed enqueue) is leading. Do not let one stand in for the other, and do not let depth drive the stall page when age would fire first.
- The per-outbox backlog breakdown already exists; this ticket surfaces it as a breakdown rather than a total, so a stuck module is identifiable. Reuse the existing figures rather than recomputing them.
- "Recent activity", never "concurrency", in the API field name as well as the label. Both are named criteria. The real concurrency gauge lives in the tracing backend and is a link, not a number stored here.
- The enqueue event fires when work **enters** the pipeline. Publish it in the same transaction as the work item's creation, and register it in the event registry in this ticket.
- #734 adds the remaining reliability alert kinds on top of this ticket's queue-age alert; #738 renders depth and age.
