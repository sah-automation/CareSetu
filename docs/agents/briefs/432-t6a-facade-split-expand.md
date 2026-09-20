# Brief - T6a PHASE-8 review-close: facade split (expand) - two state-machine facades + thin compatibility wrapper

**Ticket:** #432 · **Parent:** #426 · **Refreshed:** 2026-09-15
**Reading surface:** ~9.6K tokens (budget 10K) - within budget (facade body already loaded from T2/T3/T4 context)

## Scope

Phase-8 review-close T6a (facade split, expand step). The care facade is physically reorganized along its two state machines so each half is small enough to navigate and test on its own: a case-console facade (handshake, open-cases list, case read, close-without-prescription) and a prescription facade (rx draft, revision, approve, reject, get approved). The shared ownership guard and envelope builders are shared, not duplicated. The existing facade remains as a thin compatibility wrapper delegating to the two, so app wiring, routes, and every existing test stay green untouched. Recurring case/prescription/doctor parameter clumps are bundled where it reduces noise, without introducing a new module boundary.

Acceptance criteria (verbatim from ticket):

- [ ] Two new facade classes exist with operations partitioned by state machine; shared helpers are imported, never copied
- [ ] The existing facade is a thin wrapper delegating to the two; no behaviour change (existing suite green with zero route/test edits)
- [ ] No new module boundary or duplicate ownership-guard copy exists
- [ ] `npm run test:unit:backend`, `npm run lint`, `npm run typecheck`, `npm run scan` all green

**Blocked by:** #431 (T5) - route call targets stay stable through the expand step.

## Read-list (in order)

1. `care/facade.py` - the full public/private-method inventory to partition. Public ops by machine: case-console = `mark_consult_complete` + `get_case` + `list_doctor_cases` + `submit_doctor_input` + T3's `close_case_without_rx`; prescription = `create_rx_draft` + `save_rx_revision` + `approve_prescription` + `reject_prescription` + `get_approved_prescription`. Shared helpers to import (never copy): the one ownership guard from #430 (T4), `_to_case_detail`, `_to_rx_item_view`, `_derive_edited_yn`, `_assemble_history_summary`, the envelope builders. Structural/skim read - bodies already loaded in T2/T3/T4. (~6.5K)
2. `care/care_models.py` - the DTO/view models both facades return (no new DTOs expected; the parameter-clump bundling may introduce small request-context dataclasses). (~1.5K)
3. `app/main.py` care wiring slice (~L290-300) - where `CareFacade(engine=..., intake_facade=..., health_facade=...)` is constructed; the wrapper regresses back into context for foreign construction. (~0.6K)
4. `worker/main.py` (~L66-112) - `register_handlers` composition root: adapters registration is facade-construction-wise separate, confirm it needs no change in this expand step. (~0.5K)
5. `scripts/check_module_boundaries.py` (T6a checker, run by lint) - confirm no new cross-schema/module imports are introduced by the split files; care stays one module. (~0.5K)

## Do NOT read

- Intake/partner/iam internals, idempotency internals, the state-machine transition bodies (already canonical), the frontend, `docs/archive/`.
- Route and test file bodies - skim only to confirm they import the facade class name (zero edits in this ticket).

## Baseline verify (must pass before the first edit)

Confirmed green on this tree (HEAD `a472db1`, 2026-09-15): `npm run test:unit:backend` (2076 passed), `npm run migration-check` (single head, no cross-schema FK), `npm run lint` (all hooks passed), `npm run typecheck:backend` (no issues).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - full suite green with ZERO route/test edits (proves the wrapper is behaviour-identical)
- `npm run lint` - includes the module-boundary checker
- `npm run typecheck`
- `npm run scan`

## Handoff notes

- Structure: add two concrete classes (e.g. `CaseConsoleFacade` and `PrescriptionFacade`) sharing one ownership-guard import and the shared view/derive/assemble helpers via import, never copy; keep `CareFacade` as a thin delegating wrapper with an identical public signature so `app/main.py`, routes, and every test keep constructing `CareFacade` unchanged.
- Constructor seams stay symmetric: both new facades take `engine`; the prescription facade needs `intake_facade` (AI draft via `request_rx_draft`) and `health_facade` (consent-gated history); the case-console facade needs `intake_facade` (`get_finalized_pre_summary`). The wrapper constructs both.
- `internal-modules.md` §3.6 and the coding standard §8 ("split large facades along their state machines") are the normative backing for this ticket.
- This is the **expand** step: no route/test/behaviour edits at all. T6b (#434), serialized after this, deletes the wrapper and re-points wiring/tests - keep the wrapper's method names identical to today's `CareFacade` so T6b's migration is purely mechanical.
- Do NOT invent a new event, schema, or module boundary; care stays one module (the boundary checker in lint enforces it).
- If the facade has drifted since these briefs (check #426's closing comments and the outputs of #427-431), re-verify the method inventory before partitioning.
