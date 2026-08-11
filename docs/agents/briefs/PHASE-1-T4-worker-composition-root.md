# Brief — 30 PHASE-1 T4: Worker process + composition root

**Ticket:** #30 · **Parent:** #16 · **Refreshed:** 2026-08-11
**Reading surface:** ~6K tokens (budget 10K) — within budget

## Scope

The separate async worker process: an entrypoint that builds the `HandlerRegistry`
from each module's `register_handlers` at the composition root, runs the dispatcher
loop, and drains gracefully on SIGTERM.

Acceptance criteria (verbatim from #30):

- [ ] Worker entrypoint starts the dispatcher loop as a separate process
- [ ] Composition root wires module `register_handlers` into the registry (modules never import each other)
- [ ] SIGTERM triggers graceful drain of inflight claims
- [ ] Unit test proves the drain/shutdown path

## Read-list (in order)

1. Issue #16 `Implementation Decisions` — the **Worker process** bullet: separate
   async process, dispatcher poll loop, graceful SIGTERM drain; and the composition-root
   rule (infra imports modules only at the composition root) (~2K, via `gh issue view 16`).
2. `apps/backend/bus/dispatcher.py` — `run_poll_loop` (already honours `stop_event`
   between passes so the pass in flight drains; exceptions propagate), `discover_outbox_tables`
   (list-based discovery), `OutboxTable`, `DispatcherConfig`, `DEFAULT_DISPATCHER_CONFIG` (~1.5K).
3. `apps/backend/bus/registry.py` — `HandlerRegistry` + the docstring's composition-root
   contract: "built ... from each module's `register_handlers` callbacks" (~0.5K).
4. `apps/backend/app/config.py` — `Settings` / `get_settings` (env-driven `database_url`,
   resolved once) and `apps/backend/bus/bootstrap.py` — `MODULE_SCHEMAS` (the 11 canonical names) (~0.3K).
5. `apps/backend/scripts/check_module_boundaries.py` — `_iter_checked_files`,
   `_violation_message`, `DEFAULT_CARVE_OUT_RELATIVE_ROOTS`, `SCHEMA_PLUMBING_PACKAGES`:
   the worker's module-`adapters` imports must be carve-out-whitelisted or the CI gate fails (~1.5K).
6. `apps/backend/scripts/scaffold_module.py` + `tests/unit/test_module_layout.py` —
   the `adapters/__init__.py` template the new `register_handlers` seam extends (~0.5K).
7. Test patterns: `tests/unit/test_dispatcher.py` (stop-event unit pattern),
   `tests/integration/test_dispatcher.py::test_run_poll_loop_drains_discovered_outbox_tables`
   (the drain proof that already exists at loop level) (~0.5K).

## Do NOT read

- `docs/archive/`, `phase0/`, `apps/frontend/`.
- Gateway stubs (#29), ledger/outbox_writer internals, alembic harness, the CI workflow.
- APScheduler: issue #16 mentions a scaffold "no jobs yet", but ticket #30's ACs do
  not require it and it is not a dependency; the roadmap defers APScheduler to Phase 12/13.
  Do not add the dependency.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run test:integration`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` (new `tests/unit/test_worker.py`: composition-root wiring + drain/shutdown path)
- `npm run typecheck:backend` and `npm run lint:backend`
- `npm run check:boundaries` (worker carve-out must pass the isolation gate)
- `npm run test:integration` (loop-level drain stays green)

## Handoff notes

- Baseline verified green on 2026-08-11: 250 unit + 21 integration passed.
- **Graceful drain already lives in the loop:** `run_poll_loop` honours `stop_event`
  between passes — the current pass finishes so inflight claims drain before shutdown.
  The worker's job is SIGTERM → `stop_event.set()`; the loop does the rest. Do not
  reimplement drain in the worker.
- **The `register_handlers` seam does not exist yet.** Each of the 11 modules' empty
  `adapters/__init__.py` gets `register_handlers(registry: HandlerRegistry) -> None`
  (no-op in Phase 1 — no business handlers). Update the generator template in
  `scaffold_module.py` too and hand-write the 11 existing trees to match (the generator
  never rewrites an existing file).
- **Composition root = static imports in the worker entrypoint.** Use
  `from modules.<name>.adapters import register_handlers` for all 11, in
  `MODULE_SCHEMAS` order. Do not use dynamic `importlib` — static imports are
  gate-visible and mypy-strict friendly.
- **Boundary checker needs one additive change:** add `worker` to
  `DEFAULT_CARVE_OUT_RELATIVE_ROOTS` and allow the worker carve-out to import module
  `adapters` only (the composition-root seam), keyed off the carve-out root's name
  (`root.name == "worker"`). `domain`/`schema`/`outbox`/`facade` imports from the worker
  must still be rejected. Update `test_real_module_tree_passes` and add a fixture test.
- **Windows signal caveat:** `loop.add_signal_handler(signal.SIGTERM, ...)` raises
  `NotImplementedError` on Windows; the worker must fall back to `signal.signal`. Return
  the installed callbacks from the wiring function so the unit test can drive the
  shutdown path without OS signals. Production target is Linux (staging VM).
- **New package** `apps/backend/worker/` with `__init__.py` + `main.py`
  (`python -m worker.main` from `apps/backend`; separate process). No APScheduler.
- Keep the worker's `DispatcherConfig` and `Settings` injectable so tests need no DB.
