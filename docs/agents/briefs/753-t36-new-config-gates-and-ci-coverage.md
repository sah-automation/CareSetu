# Brief - #753 New configuration gates and CI gate-job coverage

**Ticket:** #753 · **Parent:** #717 · **Refreshed:** 2026-10-22
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

Put every new feature behind a configuration gate that is disabled by default, additive, and degrades to a no-op - and prove the no-op path in CI, because a no-op path is what rots silently. Extend the existing gates boot job rather than adding a new one.

- [ ] Every new gate is declared on the settings object, disabled by default, additive, and degrades to a no-op.
- [ ] The CI job that boots the observability gates on and off covers the new gates, so the inert path cannot rot.
- [ ] Each new gate's off path boots the application and answers healthy, exactly as the existing gates are proven.
- [ ] No gate changes existing behaviour when it is off.
- [ ] The gate posture report covers the new gates alongside the existing ones.
- [ ] Example deployment environment files document the new variables.

## Read-list (in order)

1. Spec #717 - Implementation Decision 45; the known-ceiling and compliance notes that make gating load-bearing. (~0.8K)
2. The settings object's existing observability gate block, its validation rules and the comment that already documents the "additive, disabled by default" rule. (~1K)
3. The gate-check script the CI job runs: how it reports posture, drives the ASGI lifespan and asserts health. (~0.8K)
4. The CI workflow's gate matrix job - the matrix axis, the per-gate environment variables it flips, and the dead endpoints it uses in the "on" case. (~0.9K)
5. Each feature this ticket gates, in its no-op path: the error capture seam, the per-minute HTTP counter, the collector configuration, the langfuse batch pull, the evaluators and the annotation queue. You gate what already exists; you do not build it. (~1K)
6. The example deployment environment files that document variables. (~0.5K)
7. The standards for configuration-gated features: additive, default-off, graceful degradation, no schema change outside a migration. (~0.5K)

## Do NOT read

- `docs/archive/`.
- The read query internals, the frontend, the intake and care modules.
- The Grafana assets (#748) beyond knowing what the collector gate covers.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend`
- `npm run typecheck`

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run typecheck`
- `npm run lint`
- The gate-check script, in both matrix states: the same command the CI job runs, with gates off and with gates on.

## Handoff notes

- **Extend the existing job, do not add a second one.** Two gate jobs means two places a gate can be forgotten, which is the rot this criterion exists to stop.
- The "on" case uses deliberately dead endpoints so exporters fail and are swallowed. If a new gate's failure path throws instead of degrading, the CI job will catch it - that is the point of the on-state.
- `OBSERVABILITY_ENABLED` is already declared but not read at runtime. If a new gate makes it meaningful, wire it deliberately and update the comment that says it is reserved; if not, leave it alone rather than quietly repurposing it.
- Every new gate needs both a default value and an example-environment entry. A gate documented only in the settings object is a gate nobody can turn on.
- **Refreshed 2026-10-22 (#757).** The gate set grew by one: the per-minute HTTP counter is now behind `HTTP_COUNTER_ENABLED` (#727), because a counter that counts every request in every deployment is not a gate the operator can decline. The off path installs no middleware, counts nothing and registers no fold job; the on path is unchanged. `HTTP_COUNTER_ENABLED` is in the CI gate matrix and in the posture report beside the others. The error capture's module default also moved to off, so `ERROR_CAPTURE_ENABLED` now decides it rather than the other way round - the same posture, declared in one place.
