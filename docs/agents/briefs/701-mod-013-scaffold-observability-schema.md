# Brief - 701 B3 - MOD-013 scaffold + v9_0\_\_init_observability migration + registration

**Ticket:** #701 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Scaffold the new **MOD-013 Observability** module and its private `observability` schema, as a sibling of MOD-011 Audit. One additive migration (`v9_0__init_observability`) creates the schema and its six tables plus the module's own outbox and `obs_consumed_events` ledger: `obs_ai_usage_daily`, `obs_ai_cost_budget`, `obs_ai_provider_health`, `obs_business_daily`, `obs_alert_events`. Register `observability` as the twelfth entry in `MODULE_SCHEMAS` (`bus/bootstrap.py`) and mirror it in the worker's ordered register list so the boot-drift gate stays green. The module is telemetry, not a domain bounded context; it owns its schema and consumes existing outbox events.

### Acceptance criteria

- [ ] `observability` added to `MODULE_SCHEMAS` and to the worker's `_MODULE_REGISTERS` in the same order; the boot-drift assertion passes.
- [ ] One additive `v9_0__init_observability` migration creates the schema, the five aggregate tables, the module outbox, and the ledger; `npm run migration-check` stays single-head.
- [ ] An empty `register_handlers` is wired so `build_registry` includes the module.
- [ ] The bootstrap-schemas integration test's expected-table sets are extended for `observability`.
- [ ] `npm run typecheck`; `npm run test:unit:backend`; `npm run migration-check` pass.

## Read-list (in order)

1. `bus.bootstrap.MODULE_SCHEMAS` - the canonical tuple (11 entries today); `observability` is appended as the twelfth, and the module name is the schema name and the register function's package segment. (~0.2K tokens)
2. `worker.main._MODULE_REGISTERS` + `_assert_registers_mirror_schemas` + `build_registry` - the ordered tuple that must mirror `MODULE_SCHEMAS` (the check derives each name from `register.__module__.split(".")[1]`), so `observability_register_handlers` must be added at the matching position. (~2.5K tokens)
3. The MOD-011 audit layout as the sibling precedent: `modules.audit.schema.models` (`MODULE_METADATA = MetaData(schema="audit")`, `outbox_table(...)`, `consumed_events_table(...)`), `modules.audit.outbox` (`AUDIT_OUTBOX_TABLE`), and `modules.audit.adapters.register_handlers` (an empty body is enough for B3; B4a fills it). (~3K tokens)
4. `v7_0__init_intake` migration - the one-migration shape to copy: `CREATE SCHEMA IF NOT EXISTS`, the aggregate tables, the `<module>_outbox` table matching `bus.outbox_ddl.outbox_table`, the `consumed_events` ledger matching `consumed_events_table`, the poll index, and a symmetric `downgrade`. (~2K tokens)
5. `tests.integration.test_bootstrap_schemas` - the `EXPECTED_*_TABLES` sets and the set-equality assertion against the live schemas; add an `EXPECTED_OBSERVABILITY_TABLES` set (aggregate tables, outbox, ledger). Also note `non_system == set(MODULE_SCHEMAS)` is asserted. (~2K tokens)
6. The parent plan's §7.1/§7.2 - the MOD-013 spec (sibling of MOD-011, twelfth `MODULE_SCHEMAS` entry, one-schema-rule extension) and the six-table column shapes. (~1K tokens)
7. `scripts.scaffold_module._MODULE_SPEC_TUPLES` and `tests.unit.test_module_layout` - the per-module `(title, mod_id)` tuples are zipped onto `MODULE_SCHEMAS` and raise `RuntimeError` on length drift, so a twelfth tuple (`("Observability", "MOD-013")`-style) is required or the generator and its test fail. (~0.8K tokens)
8. `scripts.check_module_boundaries.check_namespace_prefixes` - enforces that every `Table(...)` statically named in `modules/<module>/schema/models.py` starts with `<module>_`, and that `outbox.py` declares `<MODULE>_OUTBOX_TABLE = "<module>_outbox"`. (~0.5K tokens)

## Do NOT read

- The consumer logic (B4a) and the rollup (B5a/B5b).
- The frontend.
- Unrelated modules and migrations.

## Baseline verify (must pass before the first edit)

- `npm run typecheck` - PASS (current tree)
- `npm run test:unit:backend` - PASS (2925 passed)
- `npm run migration-check` - PASS (single head today at `v8_18`, revision `5a6fc4715675`)

## Done-verify (acceptance criteria -> commands)

- `npm run typecheck`
- `npm run test:unit:backend`
- `npm run migration-check` (single head; no cross-schema FK)
- `tests/integration/test_bootstrap_schemas.py` (needs local native PostgreSQL; skips if unreachable)

## Handoff notes

- New migration's `down_revision` is the current head `5a6fc4715675` (`v8_18__access_history_purge_self_rows`); keep it a single additive head.
- Register the module via the static import list at the worker composition root - no dynamic `importlib` (the drift assert runs at import).
- Two naming conflicts must be resolved before writing the migration and models, because the machine gates disagree with the plan/issue wording:
  1. `check_module_boundaries` requires the `observability_` table prefix, but the plan/issue name the aggregates `obs_ai_usage_daily`, `obs_alert_events`, etc. Either rename to `observability_*` or register a documented exception (the `care` facade split is the precedent for a sanctioned deviation).
  2. The shared harness (`bus.handler_harness.run_handler` -> `bus.ledger.record_consumed_event` -> `consumed_events_table(schema)`) hardcodes the ledger table name `consumed_events`; the plan/issue call it `obs_consumed_events`. Using the plan name means B4a cannot use the shared harness it is required to use. Recommend the standard `observability.consumed_events` unless a deliberate exception is recorded.
- Do not add cross-schema foreign keys - `npm run migration-check` scans for them and the module isolation rule forbids them.
