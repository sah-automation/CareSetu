# Brief - #735 Alert acknowledgement endpoint

**Ticket:** #735 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Let an operator acknowledge an alert, which finally writes the acknowledgement columns that have existed on the alert row since the first observability migration and have never been written by anything. An acknowledged alert stops looking like an open problem, and the response becomes attributable.

- [ ] A single acknowledgement endpoint writes the acknowledging operator and the timestamp, and moves the alert to the acknowledged status.
- [ ] Acknowledgement and the resolved state both appear in the alert status filter.
- [ ] Acknowledged alerts are filterable separately from open ones, so an operator can work the open list.
- [ ] The endpoint sits behind the same flat operator requirement as the existing reads, and an unauthenticated caller gets nothing.
- [ ] Acknowledging the same alert twice is idempotent - the first acknowledgement stands.
- [ ] The acknowledgement is written on the alert row that already exists; no new table and no migration.

## Read-list (in order)

1. Spec #717 - Implementation Decision 19; Implementation Decision 44 (one acknowledgement write, flat operator requirement). (~0.7K)
2. `docs/standards/api-standards.md` - write-route conventions, RBAC, validation, and the error envelope for a write. (~1K)
3. The alert event table - its status column's existing values, and its two acknowledgement columns that are currently selected but never written. (~0.6K)
4. The existing alert read and its status filter, including how status is indexed. (~0.6K)
5. One existing operator **write** route end to end - its authentication requirement, its validation and its conflict handling - and copy it. (~1.2K)
6. How the operator's identity reaches a backend route: the request principal, and what to store in the acknowledging-operator column. (~0.7K)
7. The read-route round-trip integration test - extend it for the write, the filter, the idempotency case and the unauthenticated caller. (~1K)

## Do NOT read

- Frontend sources beyond confirming no client contract changes - the alert feed consumes the widened status filter that #738 renders.
- The alert kinds and the rollup - #734 owns those.
- `docs/archive/`, the intake and care modules, the vendor exporters.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- The columns already exist. If you find yourself writing a migration, you have misread the ticket - that failure is one of the acceptance criteria.
- `acknowledged` joins `open` and `resolved` as a third status value. Any existing equality-to-two-values assumption in a filter or a test must be widened deliberately, and the acknowledgement status must appear in the filter list.
- Idempotency means the _first_ acknowledgement stands: a second acknowledgement must not overwrite the original operator or timestamp. Decide the conflict rule and make it observable in the response.
- The operator column stores an identity reference, not a display name - keep it consistent with how the rest of the platform records "who did this".
- #738 renders the acknowledgement from the console. It depends on this ticket, not the other way round.
