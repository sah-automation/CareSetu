# Brief - 391 Contract pin for degraded signature

**Ticket:** #391 · **Parent:** #388 · **Refreshed:** 2026-09-12
**Reading surface:** ~3.5K tokens (budget 10K) - within budget

## Scope

A contract test pinning the API shape the degraded frontend branch depends on: for a Ready-for-Review intake with no pre-summary row, the pre-summary endpoint returns the not-found envelope and the intake-detail endpoint reports `ready_for_review`. No endpoint behavior changes; the test pins identical signaling that already exists.

Acceptance criteria:

- [ ] Contract test asserts the pre-summary endpoint returns the not-found envelope (`INTAKE_NOT_FOUND`) for a Ready-for-Review intake with no pre-summary row
- [ ] Contract test asserts the intake-detail endpoint returns status `ready_for_review` for the same intake
- [ ] Test passes against current code unchanged (pins existing behavior, drives no code change)

## Read-list (in order)

1. Intake HTTP surface `get_pre_summary` and `get_intake` in `apps/backend/modules/intake/adapters/routes.py` - their not-found/error-envelope behavior and the envelope shape a Ready-for-Review intake with no pre-summary row produces (~1K)
2. Existing intake route/API contract unit tests under `tests/unit` - the app/test-client harness and the `INTAKE_NOT_FOUND` envelope prior art (grep `get_pre_summary` / `INTAKE_NOT_FOUND` in `tests/unit` to find the harness to mirror) (~2K)

## Do NOT read

- Pipeline internals · AI gateway adapters · frontend · `docs/archive`

## Baseline verify (must pass before the first edit, verified 2026-09-12)

- `npm run test:unit:backend` - 1723 passed, 3 pre-existing failures unrelated to intake (`test_app_shell.py::test_dev_otp_gated_outside_dev_test_environment`, `test_app_shell.py::test_mock_sms_adapter_stored_in_demo_mode_but_not_production_default`, `test_seed_demo.py::test_otp_surface_disabled_by_default`)
- `npm run typecheck` - backend mypy clean (213 files); frontend tsc blocked by stale `.next/dev` artifacts (unrelated to this ticket)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - the new contract test green alongside the intake route/AI suites
- `npm run typecheck` - backend clean

## Handoff notes

- Pure test ticket: drives no endpoint change. It locks the exact signature (status `ready_for_review` + not-found envelope) that tickets #389/#390 branch on.
- If building a "Ready-for-Review intake with no pre-summary row" in the test harness is awkward because the pipeline normally creates the row, construct the intake state at the DB/fixture level (insert intake + transition to Ready-for-Review without a pre-summary row) rather than driving the full AI pipeline.
- Do not introduce a degraded marker or endpoint - the issue explicitly keeps the API contract unchanged.
