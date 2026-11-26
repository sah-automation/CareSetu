# Brief - #730 Live error feed read

**Ticket:** #730 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Serve a live, unified error stream from Postgres - the system of record - so failures are visible as they happen rather than reconstructed from a nightly rollup. Repeated identical failures collapse into one navigable entry instead of burying every other error.

- [ ] The live error feed is paged, and repeated identical failures collapse into one entry carrying an occurrence count and a most-recent timestamp.
- [ ] Every entry shows the templated route, the method and the status code - never a raw request path.
- [ ] Every entry carries the trace identifier that joins to the tracing backend.
- [ ] Entries are filterable by open and resolved, so a live problem is separable from a handled one.
- [ ] The read sits behind the same flat operator requirement as the existing nine reads.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 12, 13, 14; the error-feed user stories; Out of Scope (Sentry as a queryable store). (~1K)
2. `docs/standards/api-standards.md` - the read conventions, pagination conventions and RBAC for an operator read. (~1K)
3. The error event table and the fingerprint #726 established - its stability properties and which attributes it excludes. (~0.7K)
4. One existing operator read end to end - route, facade, query, domain dataclasses, wire decimals - as the shape to copy. (~1.8K)
5. An existing paged read if one exists, to copy its paging contract; otherwise the read that already returns a page wrapper. (~0.7K)
6. The status vocabulary on captured errors, and how #735's acknowledgement status interacts with this filter. (~0.5K)
7. The read-route round-trip integration test - extend it: paging, collapse with a count, filtering, and the trace identifier surviving to the wire. (~1.1K)

## Do NOT read

- Frontend sources, `docs/archive/`.
- The gateway error seam internals (#726) beyond the table and fingerprint you read.
- The counter read (#727), the provider board (#728), the reliability page (#738).
- The Sentry integration beyond the deep link #736 builds.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- Collapse by fingerprint, then count. "N identical errors" and "N distinct errors" are different pages; make the distinction visible in the response so the client can label it.
- A collapsed entry's timestamp is the most recent occurrence, not the first. An operator reading a feed wants to know when it last happened.
- The feed is served from Postgres, not Sentry. Sentry is a crash tracker and a deep-link target; do not proxy a query to it from here.
- Filter states must compose with #735's acknowledgement status. If #735 has landed, all three states are filterable; if not, leave the status set open rather than hard-coding two.
- An empty feed is an ambiguous signal. The capture-liveness indicator from #727 is what disambiguates it - reference it in the page rather than duplicating it here.
