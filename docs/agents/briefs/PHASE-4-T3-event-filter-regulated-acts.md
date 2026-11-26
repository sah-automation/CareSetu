# Brief - T3 Event filter for regulated acts

**Ticket:** #237 · **Parent:** #234 PHASE-4 · **Refreshed:** 2026-08-27
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

Implement a predicate function that classifies any `audit.event` payload as a regulated act (append to hash chain) or operational event (skip). Pure logic, no database writes.

Acceptance criteria: see #237 body verbatim.

## Read-list (in order)

1. `docs/architecture/internal-modules.md` - section 4.2 event registry for the full event type list and producer modules (~1.5K)
2. `docs/roadmap/implementation-roadmap.md` - PHASE-4 section for the regulated-act scope list (~0.5K)
3. `apps/backend/bus/events.py` - existing event type constants (~0.3K)

## Do NOT read

- Other module code, schema files, bus infrastructure internals, docs/archive/.

## Baseline verify (must pass before the first edit)

For this ticket: `npm run test:unit:backend`.

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` (all filter tests green)

## Handoff notes

- `REGULATED_ACT_TYPES: frozenset[str]` containing the ~23 regulated-act event types from the spec.
- `is_regulated_act(event_type: str) -> bool`: returns `event_type in REGULATED_ACT_TYPES`. Unknown types return False (conservative).
- Place in `modules/audit/domain/event_filter.py` or similar within the audit module.
- Regulated acts: consent lifecycle, record access/denial, prescriptions, diagnostics, settlements, partner decisions, patient lifecycle.
- Operational (skip): notifications, OTPs, metrics, order lifecycle, intake pipeline, case consult.
