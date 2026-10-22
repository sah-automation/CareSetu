# Brief - 715 D2b - internal-modules sync matrix + traceability (MOD-013 rows)

**Ticket:** #715 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~6K tokens (budget 10K) - within budget

## Scope

Register MOD-013 in two of the cross-reference matrices of `docs/architecture/internal-modules.md`: the `§4.1` module-sync matrix and the `§5` feature↔module↔storage traceability. Read each of those two matrix sections whole (they are the single source of truth for edges) and add MOD-013 rows consistently with how MOD-011 is registered. Do not invent new module links. The `§4.2` event registry is a separate ticket.

Acceptance criteria (verbatim from the ticket):

- [ ] `§4.1` sync matrix gains the MOD-013 row(s), consistent with MOD-011.
- [ ] `§5` traceability gains the MOD-013 rows mapping the observability features to storage.
- [ ] No cross-schema edge invented.
- [ ] `npm run lint` passes.

## Read-list (in order)

1. `docs/architecture/internal-modules.md` `§4.1` Synchronous Communication Matrix, whole - the row/column shape and the "how MOD-011 appears" convention (the `Operator / Patient channel → MOD-011 (Audit)` row plus the actor`(channel)` initiating-label convention); the MOD-013 operator-facing sync edges belong here (~3.0K tokens).
2. `docs/architecture/internal-modules.md` `§5` System-Wide End-to-End Traceability Matrix, whole - how MOD-011 is carried across the `FEAT-003`/`FEAT-015`/`FEAT-016`/`FEAT-020` and `NFR-001/002` rows, and the `PHASE-8.1`/batch non-FEAT row convention to mirror for the observability phase; the MOD-013 observability-to-storage rows belong here (~2.4K tokens).
3. The new `MOD-013 Observability` block in `docs/architecture/internal-modules.md` `§3`, added by D2a (#713) - its Primary Scope, Traceability Link and stated facade/HTTP surfaces fix exactly which MOD-013 edges the two matrices may register (~0.7K tokens; blocked-by dependency - read only once D2a has landed).

## Do NOT read

- `§4.2` Asynchronous Event Registry and any MOD-013 event subscriptions - that is D2c (#716).
- `docs/architecture/system-context.md` and the observability ADRs (D1, #711); `docs/roadmap/implementation-roadmap.md`, `docs/standards/*`, the deployment plan, and `CONTEXT.md` edits (D3, #714).
- The other module specs (`§3.1`-`§3.12` and the `§3.13` profile-media adapter) - only the D2a MOD-013 `§3` block is in scope - plus the `§2` diagrams and `§6` checklist.
- `docs/prd/project-prd.md`, `docs/archive/`, and all source code.

## Baseline verify (must pass before the first edit)

- `npm run lint` (pre-commit `run --all-files`) is the docs gate; it auto-reformats `.md` (prettier) and runs the no-em-dash (use `-`, never U+2014) and legacy-event-name hooks. Status: not run in this research-only session; `git status` already carries unrelated `M`/`??` entries (for example `apps/frontend/src/app/globals.css`, the deleted `docs/plans/plan-post-phase14-observability.md`) - do not treat those as yours. Run it on the untouched tree before the first edit.

## Done-verify (acceptance criteria → commands)

- `npm run lint` - green.
- Grep gate: `§4.1` gains MOD-013 row(s) in the same Initiating / Target / Protocol / Data Schema / Purpose / Traceability shape as MOD-011's row, each target an existing module or actor - no invented link.
- Grep gate: `§5` gains row(s) mapping the observability features/phase to `MOD-013` and the `observability` schema, in the existing column shape.
- Diff gate: additive rows only - no existing row rewritten, no new event name, and no `§4.2` edit.

## Handoff notes

- Sibling boundaries in the D re-cut: D2a (#713) owns the MOD-013 spec block; D2c (#716) owns the `§4.2` event registry; D1 (#711) owns the ADRs and `system-context.md`; D3 (#714) owns the roadmap, the two standards docs, the deployment plan, and `CONTEXT.md`. This ticket owns ONLY the `§4.1` and `§5` matrix rows in `internal-modules.md`.
- Blocked by #713: if the MOD-013 spec block is not present, stop - the matrices must match the spec. With the spec present, derive each MOD-013 row from the interfaces it states; introduce no edge the spec does not state.
- The `§4.2` event registry is out of scope even though MOD-013 consumes events - leave every subscriber cell untouched for #716.
