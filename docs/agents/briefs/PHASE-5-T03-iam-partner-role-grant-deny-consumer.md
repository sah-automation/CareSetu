# Brief - T03 IAM event-driven partner role grant/deny

**Ticket:** #248 · **Parent:** #243 · **Refreshed:** 2026-08-31
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

The MOD-001 (iam) async consumer that makes access follow verification state: grant the `partner` role to a partner's identity when they are `[Active]` (`partner.activated`) and deny it when they are `[Rejected]` (`partner.rejected`), and suspend via the deactivation path (`credential.invalidated`). This is the activation-gated step that completes the access model - account creation is T02 (#245); this ticket closes the loop by subscribing to terminal lifecycle events and mutating `iam_role_grants`.

Implementation:

- In iam, subscribe to `partner.activated` -> grant the `partner` role on the partner's identity; subscribe to `partner.rejected` (and the deactivation path via `credential.invalidated`) -> deny/suspend the `partner` role.
- Follow the repo's async consumer pattern (idempotent via the `consumed_events` ledger, written in the same transaction as the grant/deny - see the audit consumers and `record_consumed_event`).
- Uses T02's account-creation seam as the counterpart so the identity exists before the role grant.

Acceptance criteria (from #248 body):

- [ ] `partner.activated` leads to the `partner` role granted in iam (observable through the iam facade, not internals)
- [ ] `partner.rejected` / `credential.invalidated` leads to the `partner` role denied/suspended
- [ ] Consumer is idempotent (replay-safe via consumed-event ledger) - mirrors `test_audit_consumer.py`
- [ ] Unit + integration test covers the event chain `partner.activated`/`rejected` -> role grant/deny
- [ ] `npm run test:unit:backend` and `npm run typecheck` pass

## Read-list (in order)

1. `apps/backend/modules/audit/adapters/__init__.py` - THE canonical consumer pattern: `register_handlers` seam, `_run_handler` boilerplate (payload extraction, `record_consumed_event`, `delivered` skip), ledger-first-then-effect idempotence, `_delivery_engine()` stub (195 lines, ~2.5K)
2. `apps/backend/modules/iam/adapters/__init__.py` - the current empty iam `register_handlers` to fill in (12 lines, ~0.2K)
3. `apps/backend/bus/ledger.py` - `record_consumed_event()` (returns `True` first-delivery / `False` replay) (~0.7K)
4. `apps/backend/bus/registry.py` - `HandlerRegistry`: `register`, `register_payload_model`, `handlers_for` (~0.8K)
5. `apps/backend/bus/events.py` - canonical event constants `partner.activated` / `partner.rejected` / `credential.invalidated` (already literals in `REGULATED_ACT_TYPES`) to import, not re-declare (~1.2K)
6. `apps/backend/modules/iam/schema/models.py` - `iam_role_grants` (`role` constraint `('patient','partner','operator')`, `status` `('Active','Suspended')`) - the row the handler inserts/updates (~1.5K)
7. Role grant/deny mechanics: `apps/backend/modules/iam/otp_facade.py` (~line 326) `_grant_patient_role` (idempotent insert) and `apps/backend/modules/iam/session_facade.py` (~line 361) `_resolve_active_role` (grant row read) - the existing grant/suspend patterns to mirror (~1.2K)
8. `apps/backend/worker/main.py` (imports + `build_registry` only) - confirms `iam_register_handlers` is already in `_MODULE_REGISTERS`; no composition-root change needed (~1K, skim)
9. `tests/unit/test_audit_consumer.py` (skim: the `_registered_handler`, `_fake_engine`, ledger-first + replay-skip tests; skip the hash-chain-specific assertions) - the test harness pattern to mirror (~3K, skim)

## Do NOT read

- `modules/partner/*` internals beyond the event names - only the events this ticket consumes matter; the producer side is a different ticket
- `modules/health/adapters/__init__.py` (optional second pattern - audit's pattern is sufficient), `bus/dispatcher.py` internals, `docs/archive/`
- The full `test_audit_consumer.py` hash-chain/`audit_events` append specifics

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (874 passed, 1 StarletteDeprecationWarning on the current tree)
- `npm run typecheck` (mypy `--strict` + tsc)

## Done-verify (acceptance criteria -> commands)

- New unit test (event chain `partner.activated` -> grant / `partner.rejected` + `credential.invalidated` -> deny/suspend, plus replay-skip idempotence) - `npm run test:unit:backend`
- `npm run typecheck` (mypy strict - typed payload models + handlers)
- `npm run test:integration` (needs local native PostgreSQL: event-chain -> role grant/deny round-trip observable through the iam facade) - skips if PG unreachable

## Handoff notes

- **Blocked by** #247 (T04 - partner lifecycle state machine + event catalog: the consumed events must exist) and dependent on #245 (T02 account-creation seam - the identity exists before this grants a role). #248 is explicitly blocked by #247, not #245, but the grant assumes the identity exists.
- Consumers are idempotent per ADR-0002 §3: `record_consumed_event` ledger row in the SAME transaction as the grant/deny; a `False` return (replay) skips the effect.
- The iam module owns the payload models for these events (consumer owns the model, cf. audit's `register_payload_model`) - register payload models for `partner.activated`, `partner.rejected`, `credential.invalidated`, or the dispatcher errors on reclaim ("no handlers registered" guard). Follow audit's `register_payload_model` + handler registration pattern.
- Grant = an `Active` `partner` role row; Deny/Suspend = flip the existing `partner` role grant from `Active` to `Suspended` (status constraint allows only these two). Deny should be idempotent even if no grant row exists.
- Do NOT grant/deny via `register_patient`/OTP machinery - this is a consumer mutating `iam_role_grants` directly through a typed facade seam (observable via the iam facade per acceptance criteria, not internals).
- `partner.activated`/`partner.rejected`/`credential.invalidated` are already-declared literals in `bus/events.py` (no new constants). They are also in `REGULATED_ACT_TYPES` for the audit chain - do not remove them.
- The worker composition root already imports `iam_register_handlers`; wiring it to register the new consumers is all that's required (no `_MODULE_REGISTERS` change).
- `test_module_layout.py` and the enforced module layout (each module's adapters has `register_handlers`) already hold - this ticket fills in iam's empty one.
