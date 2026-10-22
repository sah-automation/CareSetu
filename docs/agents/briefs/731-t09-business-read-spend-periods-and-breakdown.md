# Brief - #731 Business read: period spend, cap, projected burn and breakdown

**Ticket:** #731 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Give the operator the answer to "is this spend healthy?" - spend today, week to date and month to date side by side, against the cap with a projected month-end burn, broken out by provider, model and task type, with input and output token volumes and a cost per thousand on each side. One period-parameterised read serves all three windows, so there is one aggregation, not three.

- [ ] A single period-parameterised business read serves today, week-to-date and month-to-date; three separate reads do not exist.
- [ ] Total spend, the monthly cap, the cap consumed and a projected month-end burn are returned together, so an operator is warned before the cap rather than after.
- [ ] Spend is broken out by model provider, by model within a provider, and by task type - including `draft`, which is now a produced task type.
- [ ] Input and output token volumes are reported separately, each with its own cost per thousand tokens, so a blended average cannot hide a routing regression.
- [ ] The read sits behind the same flat operator requirement as the existing nine reads, and its wire decimals follow the existing wire-decimal convention.
- [ ] The read is computed from the daily per-actor aggregate, not from a stored second copy of the same number.

## Read-list (in order)

1. Spec #717 - Implementation Decisions 8, 9, 11; the Business user stories; Out of Scope (subscription/tier modelling, monetisation). (~1.2K)
2. `docs/standards/api-standards.md` - the operator-read conventions, the error envelope, validation and RBAC for a read route. (~1K)
3. One existing operator read **end to end** - route, facade method, query function, domain dataclasses - and copy its structure exactly. The cost read is the closest sibling; the overview read shows how multiple sections are composed. (~2.5K)
4. The wire-decimal convention: `Decimal` fields serialised as JSON strings, the quantisation helpers, and the projection tests that assert exact wire values. (~0.8K)
5. The daily per-actor aggregate from #725 - every column this read aggregates over. (~0.6K)
6. The budget snapshot table and the rollup's budget-period logic, so the cap and the consumed figure come from the same source the rollup writes. (~0.8K)
7. The read-route round-trip integration test - extend it for this read, including a minted operator JWT and a caller without the operator requirement getting nothing. (~1.2K)

## Do NOT read

- The frontend client and panel page - #737 builds the page; you change no frontend contract here.
- The unit-metric and attribution facets - #732 owns those; do not fold them into this read.
- The cost-outlier alert - #733.
- `docs/archive/`, the intake and care modules, the vendor exporters.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- One read, three periods. A closed period parameter selects today, week-to-date or month-to-date. Three route handlers over three queries is the failure mode this criterion exists to prevent.
- Projected month-end burn must state its assumption (elapsed days of the billing period, period end date). A projection with no stated basis is a guess with a decimal in it.
- Money stays in paise integers in the domain; the existing quantisation and wire-decimal rules decide what the client sees. Follow the existing reads exactly - the frontend already parses these.
- #732 extends this same read with the unit-metric and attribution facets; keep the domain dataclasses open to that without merging the two tickets' work.
