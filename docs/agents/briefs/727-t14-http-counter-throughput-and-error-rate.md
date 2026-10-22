# Brief - #727 Per-minute HTTP counter, throughput and error rate

**Ticket:** #727 · **Parent:** #717 · **Refreshed:** 2026-10-22
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Make request throughput and error rate queryable from Postgres, beyond the vendor's fourteen-day window, at the cost of one row per route per minute rather than one write per request. Give the operator a way to tell a real outage from a quiet period, and a way to tell an empty error feed from a healthy system.

- [ ] A per-minute counter keyed by route template, method and status class records one row per route per minute - never one write per request.
- [ ] Response status is collapsed to success, client-error and server-error before it is stored, so series cardinality cannot explode.
- [ ] A read gives request throughput and error rate over the recent past, so a spike is distinguishable from a trickle.
- [ ] The read exposes whether request capture itself is working, so an empty error feed is never mistaken for a healthy system.
- [ ] The application's own instrumentation is unchanged by this ticket.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 15 and 37; the throughput/error-rate and capture-liveness user stories. (~1K)
2. The per-minute HTTP counter table created by #726 - its key columns and what uniqueness it assumes. (~0.5K)
3. The ASGI middleware stack and the existing observability middleware: how a middleware is registered, what it can read off the scope (including the matched route template, not just the raw path), and where in the chain it must sit. (~1.5K)
4. One existing operator read end to end - route, facade, query, domain dataclasses, wire decimals - as the shape to copy. (~2K)
5. The status-class taxonomy already present in the observability vocabulary, if any; otherwise the one #726 established. Keep exactly one. (~0.4K)
6. The read-route round-trip integration test - extend it for throughput, error rate and the capture-liveness case (no requests at all is the interesting case). (~1.2K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The error feed read (#730) and the reliability page (#738).
- The collector configuration - #749 turns the same status-collapse rule into a shipped artefact; the application-side rule is established here.
- The intake and care modules.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- One row per route per minute is the whole point. If your design writes per request, the write amplification will show up in production before it shows up in a test.
- **Refreshed 2026-10-22 (#757).** The counter is behind the `HTTP_COUNTER_ENABLED` gate, which is OFF by default (#753): with the gate off the middleware is not installed, nothing is counted, and the worker's fold job is not registered - the no-op path, not a broken one. A verification run that drives real traffic must therefore arm the gate (`http_counter_enabled=True` on the settings object, or `HTTP_COUNTER_ENABLED=true` in the environment); the round-trip integration test does this in its counter client. The counter's own thresholds are unchanged.
- The capture-liveness signal is what stops "no errors" from reading as "healthy". It needs an explicit answer - "no requests were recorded in this window" is a different answer from "requests were recorded and none failed". Make those two distinguishable in the response.
- Route templates only, consistent with #726. The middleware must read the _matched_ route, which means it has to sit somewhere it can see the routing result.
- Last criterion is a guard rail: do not "helpfully" instrument the application further in this ticket. The cardinality firewall ships as collector configuration (#749) and the app stays as it is.
- #734's high error-rate alert and #738's throughput panel both read what you build here.
