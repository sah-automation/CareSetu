# Brief - #720 Care-attributed event at doctor selection

**Ticket:** #720 · **Parent:** #717 · **Refreshed:** 2026-10-14
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

A patient picking their doctor is invisible on the event bus, so no module may ever learn which doctor an intake belongs to without reaching into another schema. Publish a care-attributed event at the moment of the pick, carrying the intake, the patient and the doctor. Doctor attribution then rides an event rather than a join, which is the only path the module-isolation rule allows.

- [ ] Picking a doctor publishes a care-attributed event in the same transaction as the assignment write, carrying the intake reference, the patient reference and the doctor reference.
- [ ] The event name follows the registry convention and is registered in the event registry with its payload fields and subscriber intent.
- [ ] The consent grants made on the same path are unaffected and still commit together.
- [ ] No participant resolves the pairing by reading the care schema; the pairing exists only because the event said so.
- [ ] Re-publishing the same event identifiers changes nothing downstream.

## Read-list (in order)

1. Spec #717 - Problem Statement hole 2 (third bullet); Implementation Decisions 3 and 7. (~1K)
2. `docs/adr/0003-module-database-isolation.md` - the rule this ticket exists to honour, and what counts as a violation. (~0.5K)
3. `docs/architecture/internal-modules.md` §4.2 - the event naming convention (`<entity>.<past-tense-verb>`, dot-separated snake_case segments) and the row format. (~0.7K)
4. The intake facade's `pick_doctor` - the transaction it opens, the assignment column it writes, and the consent grants made inside the same transaction. (~1.2K)
5. The intake module's outbox writer and one existing intake envelope builder as the shape to copy (payload model + envelope builder + registry entry). (~1K)
6. The `partner.selected` event - the closest existing sibling that carries a doctor/partner identity; read it to see why it is _anonymous_ and therefore useless for attribution. (~0.5K)
7. `tests/unit/test_intake_events.py` - where payload shapes are asserted. (~0.5K)

## Do NOT read

- The partner directory module internals, the doctor console, the care schema models.
- Frontend sources, `docs/archive/`.
- The observability consumer and rollup - #724 consumes this event; you do not build that here.
- The consent facade beyond the grant calls already on this path.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run test:integration`
- `npm run lint`, `npm run typecheck`

## Handoff notes

- Publish **inside** the existing transaction. An event written after commit can describe a pick that rolled back - that is the bug this ticket exists to prevent.
- The doctor identifier here is a doctor, not a directory partner entry of arbitrary type; if the reference is genuinely a partner reference, say so in the payload docstring rather than pretending.
- Register the event in §4.2 in this ticket, not in the docs-reconciliation ticket (#755). §4.2 is the source of truth and an unregistered event name is an invented event name.
- Downstream, #724 writes this event's edge into the observability schema and #725 fills the doctor key on the daily aggregate. Their payload expectations must match yours exactly - change the payload and you re-open both.
