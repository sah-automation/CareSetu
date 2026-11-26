# Brief - 259 Phase-5 fix: share delivery-engine handler harness (S5)

**Ticket:** #259 · **Parent:** #243 · **Refreshed:** 2026-09-01
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

The `_delivery_engine` + `_run_handler` boilerplate (idempotent ledger-first handler loop with engine lifecycle + payload re-validation) is copy-pasted across FOUR adapter modules: `audit`, `iam`, `notify`, and `health` (finding S5). Consolidate onto one canonical harness in `bus/` (or a shared helper) and have all modules import it instead of carrying their own copies. No behavior change.

Acceptance criteria (from #259):

- [ ] `iam`, `notify`, `audit`, `health` adapters call the shared harness instead of carrying their own `_delivery_engine`/`_run_handler`; delete the per-module copies.
- [ ] Payload-model ownership stays with each consumer (each registers its own mirror; no duplicate `register_payload_model`).
- [ ] All consumer unit tests (audit/iam/notify/health) pass unchanged.

## Read-list (in order)

1. `apps/backend/bus/` - the shared home for the harness. Look at whether `bus/ledger.py` (`record_consumed_event`) is already there; decide where a `bus/handler_harness.py` (or similar) belongs. `bus/dispatcher.py` shows the fan-out + ledger contract the harness wraps (~1.5K).
2. `apps/backend/modules/audit/adapters/__init__.py` lines 71-112 - THE canonical `_delivery_engine` + `_run_handler` (imports `AUDIT_SCHEMA` from the module facade) to extract (~0.8K).
3. The near-identical copies to replace + delete: `apps/backend/modules/iam/adapters/__init__.py` (52-60, 63-93; `_IAM_SCHEMA` local const at line 49), `apps/backend/modules/notify/adapters/__init__.py` (55-63, 66-96; `NOTIFY_SCHEMA` from `modules.notify.facade`), `apps/backend/modules/health/adapters/__init__.py` (53, 64; `HEALTH_SCHEMA` from `modules.health.facade`) (~1.2K).
4. The schema constants each module's harness currently pays - the harness must accept the schema as a parameter (or the caller passes it), since each module's `record_consumed_event` uses its own schema (~0.3K).
5. The consumer unit tests: `tests/unit/test_audit_consumer.py`, `tests/unit/test_iam_*_consumer.py`, `tests/unit/test_notify_*.py`, `tests/unit/test_health_*_consumer.py` - the tests that currently `patch("modules.<mod>.adapters._delivery_engine", ...)` will need their patch target updated to wherever the shared harness lives (~2K).

## Do NOT read

- The provider/channel logic within notify's sms.py/whatsapp.py (handled by #258), partner internals, `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q` (currently 1105 passing)

## Done-verify (acceptance criteria -> commands)

- Full backend unit suite green (`node scripts/py.cjs -m pytest -c apps/backend/pyproject.toml tests/unit -q`)
- `npm run typecheck`
- Grep-verify no remaining per-module `_delivery_engine`/`_run_handler` definitions.

## Handoff notes

- S5 actually spans 4 modules (audit/iam/notify/health), not 3 - the health copy was an extra find. All four must converge on ONE harness.
- The only per-module difference is the schema constant (audit `AUDIT_SCHEMA`/iam `_IAM_SCHEMA`/notify `NOTIFY_SCHEMA`/health `HEALTH_SCHEMA`) and the schema is passed to `record_consumed_event`. Make the harness take the schema (or a `register`-time binding) as a parameter - do NOT hardcode one schema into the shared copy.
- Notify's third inline consumer `_on_notification_failed` (lines 209-244) also re-implements the same engine/lifecycle block inline - route it through the shared harness too (it needs the resolved facade, so the harness must allow the handler_fn to close over the facade, which the existing `_run_handler(envelope, payload_class, handler_fn, name)` already supports).
- The consumer unit tests patch `modules.<mod>.adapters._delivery_engine` - after the move they must patch the shared location. Plan this so no external API (console/frontend) is touched.
- Do NOT register any duplicate payload model in the shared harness - model registration stays in each consumer's `register_handlers` (module isolation).
- Related #258 (S4) edits the same notify adapters + transport.py - coordinate read/edit to avoid conflicts, or do the transport-level dedup after this harness move lands.
