# Brief - 716 D2c - internal-modules event registry (MOD-013 subscriptions)

**Ticket:** #716 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

Register MOD-013 in the `§4.2` asynchronous event registry of `docs/architecture/internal-modules.md`: list MOD-013 as a subscriber against exactly the events it consumes - `ai_job.completed`, `ai_job.failed`, `case.*`, `partner.*`, `consent.*`, `record.accessed`, and `audit.*` (including `audit.tamper_detected`). Read the registry section whole and add the rows consistently with how MOD-011's `audit.*` subscriptions are registered. Do not invent new event names; every name must already exist in the registry.

Acceptance criteria (verbatim from the ticket):

- [ ] `§4.2` event registry lists MOD-013 against exactly its subscribed events, consistent with the B4a/B4b handlers.
- [ ] No new event name is introduced; each referenced event already exists.
- [ ] `npm run lint` passes.

## Read-list (in order)

1. `docs/architecture/internal-modules.md` `§4.2` Asynchronous Event Registry, whole - one row per event with the subscribers listed in the "Subscribing Modules" cell, and how MOD-011's `audit.*` subscriptions appear, so MOD-013 is added in the same style rather than as a new row (~3.5K tokens).
2. The new `MOD-013 Observability` block in `docs/architecture/internal-modules.md` `§3`, added by D2a (#713) - its "Inbound Events Subscribed" line is the exact subscription set to register (~0.7K tokens; blocked-by dependency - read only once D2a has landed).
3. `apps/backend/bus/events.py` - only if an event-name literal needs confirming (the canonical literals behind the registry rows) (~0.4K tokens, conditional).

## Do NOT read

- `§4.1` Synchronous Communication Matrix and `§5` traceability - that is D2b (#715).
- Any other module spec (only the D2a MOD-013 `§3` block), `docs/architecture/system-context.md` and the observability ADRs (D1, #711), and the roadmap / `docs/standards/*` / deployment plan / `CONTEXT.md` edits (D3, #714).
- `docs/prd/project-prd.md`, `docs/archive/`, and any source code except `apps/backend/bus/events.py` for a name check.

## Baseline verify (must pass before the first edit)

- `npm run lint` (pre-commit `run --all-files`) is the docs gate; it auto-reformats `.md` (prettier) and runs the no-em-dash (use `-`, never U+2014) and legacy snake_case event-name hooks. Status: not run in this research-only session; `git status` already carries unrelated `M`/`??` entries (for example `apps/frontend/src/app/globals.css`, the deleted `docs/plans/plan-post-phase14-observability.md`) - do not treat those as yours. Run it on the untouched tree before the first edit.

## Done-verify (acceptance criteria → commands)

- `npm run lint` - green (the legacy event-name hook is the backstop against an invented name).
- Grep gate: MOD-013 appears in the Subscribing Modules cell of exactly the rows for `ai_job.completed`, `ai_job.failed`, `case.consult_complete` and `case.closed` (`case.*`), `consent.requested`/`consent.granted`/`consent.revoked` (`consent.*`), the `partner.*` rows, `record.accessed`, `audit.event` (generic), and `audit.tamper_detected` (`audit.*`).
- Gate: no new event row and no new event name - each referenced name already exists in the registry.
- Consistency gate: the set matches the B4a/B4b consumer handlers (#702/#703).

## Handoff notes

- Sibling boundaries in the D re-cut: D2a (#713) owns the MOD-013 spec block; D2b (#715) owns the `§4.1` and `§5` matrices; D1 (#711) owns the ADRs and `system-context.md`; D3 (#714) owns the roadmap, the two standards docs, the deployment plan, and `CONTEXT.md`. This ticket owns ONLY the `§4.2` registry rows in `internal-modules.md`.
- Blocked by #713: if the MOD-013 spec block is not present, stop - the subscriptions must match the spec's "Inbound Events Subscribed" line.
- Register by editing existing rows in place (the registry is one row per event, subscribers in a cell) - do not add event rows. The `audit.tamper_detected` row currently reads "(telemetry, alert delivery deferred)"; MOD-013 is that telemetry subscriber, so add it there. The `audit.event` (generic) row currently lists `MOD-011 (append to hash chain)`; MOD-013 is an additional subscriber alongside it.
- The `§4.1`/`§5` matrices are out of scope - leave them untouched for #715.
