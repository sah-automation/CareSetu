# Brief - #750 Langfuse daily batch pull into the observability schema

**Ticket:** #750 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Let AI quality numbers outlive the vendor's retention window by pulling Langfuse metrics into the observability schema in one daily batch, on the same schedule as the nightly rollup. No live vendor API ever sits behind a dashboard refresh, because a fast refresh could exhaust a hundred-request-a-day allowance.

- [ ] A daily batch pull moves Langfuse metrics into the observability schema, running on the same schedule as the nightly rollup.
- [ ] The pull makes no more than one metrics request per run, so it stays inside the free tier's daily request allowance.
- [ ] No live vendor API sits behind any dashboard refresh; metrics reach Postgres by batch only.
- [ ] The pull maps the vendor response into the observability schema and is safe to re-run - a second run of the same date does not double-count.
- [ ] Tested against a fake metrics API asserting that a single run makes no more than one metrics request, maps the response, and re-runs cleanly.
- [ ] No clinical content is pulled; span metadata stays on its existing allow-list.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 39 and 41; the langfuse batch-pull user stories; Out of Scope (no live vendor API behind any dashboard, no paid upgrade). (~1.1K)
2. `docs/adr/0024-*.md` - the AI tracing vendor decision and its free-tier request allowance. (~0.4K)
3. The AI tracing vendor client and its existing configuration fields, including how an unconfigured vendor no-ops today. (~0.9K)
4. The nightly rollup worker and the workflow that schedules it - the schedule and run pattern this batch joins. (~0.9K)
5. The observability facade's write path for vendor metrics, and the existing generic JSONB metric store the rollup already writes into. Reuse it rather than adding a table. (~0.8K)
6. The span-metadata allow-list that keeps PHI out of what is sent to the vendor. (~0.5K)
7. The existing test convention for an external client with a fake API double, and the fake-transport pattern used by the observability integrations. (~0.7K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The evaluators and the annotation queue - #751, #752.
- The Grafana assets (#748) and the collector configuration (#749).
- The intake pipeline internals.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- **One metrics request per run, asserted.** The allowance is a hundred requests a day across everything; the test that counts requests against a fake API is the deliverable, not a comment.
- Re-run safety: same date, no double-count. Use the existing JSONB metric store's natural key if it fits, rather than adding a table for this.
- Unconfigured vendor no-ops silently, exactly like the other vendor integrations. A missing key must not fail the nightly run.
- Run it on the rollup's schedule, or as a step after the rollup - not on its own timer. Two schedules for one system of record is one schedule too many.
- The allow-list stays as it is. If the pull needs a field the allow-list does not carry, the field needs a PHI decision, not a code change.
