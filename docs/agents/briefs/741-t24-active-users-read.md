# Brief - #741 Active users read

**Ticket:** #741 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Answer "is adoption growing?" - daily, weekly and monthly active users with a stickiness ratio, request throughput per head, and a throughput trend. Monthly active users are computed in Postgres deliberately, because the free tier's fourteen-day retention makes them structurally impossible in the vendor.

- [ ] Daily, weekly and monthly active users are returned, plus a stickiness ratio so daily usage is read against the monthly base.
- [ ] The active-actor set is derived from the product event ledger and counts a qualifying clinical action - not a login. No authentication, session or logout event is added to the registry.
- [ ] Requests per active user and total application throughput over the window are returned, plus a throughput trend.
- [ ] Monthly active users are computed in Postgres, so the reported number is not quietly truncated by a vendor retention window.
- [ ] The read sits behind the same flat operator requirement as the existing nine reads, and its wire decimals follow the existing convention.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 22, 26; the active-user user stories; Out of Scope (an authentication/session/logout domain event, and any product-analytics vendor). (~1.2K)
2. The product event ledger and daily rollup from #739 - how an actor key is stored and what a "qualifying clinical action" is in this ledger's terms. (~0.8K)
3. The per-minute HTTP counter from #727 - the throughput figures, and the window semantics it aggregates over. (~0.6K)
4. One existing operator read end to end - route, facade, query, domain dataclasses, wire decimals - as the shape to copy. (~1.8K)
5. The existing window-parameterised read (the observability reads already take a bounded window) and its validation bounds. (~0.5K)
6. The read-route round-trip integration test - extend it: DAU/WAU/MAU over a window that crosses a month boundary, stickiness, and a window wide enough to prove the number is not vendor-truncated. (~1.2K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The funnel and retention reads - #740, #742.
- The identity module's authentication flows - you read no login event because none exists and none is being added.
- The langfuse batch pull, the collector configuration, the Grafana assets.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- Weekly and monthly active users are **not** seven and thirty times today's figure; they are distinct actors over each window. A window that spans a month boundary is the test case that catches the shortcut.
- Stickiness needs a stated definition (the usual one is daily over monthly). Name it in the response or the query docstring - an unlabelled ratio is quotable out of context.
- Requests per active user divides throughput by an active-user count. Decide and state whether the denominator is the window's active users or the day's, and keep it consistent with the throughput window.
- The "no login event" criterion is a constraint, not an omission to fix. If you find yourself wanting one, the answer is a qualifying clinical action in the ledger, which is what already exists.
- A window wider than fourteen days must return real numbers. That is the whole reason this read exists.
