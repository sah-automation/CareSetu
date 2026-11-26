# Brief - 714 D3 - Roadmap PHASE-14A/B + standards + deployment plan + CONTEXT

**Ticket:** #714 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Reconcile the roadmap, standards, deployment plan, and navigation guide. Add a `PHASE-14A - Observability & Monitoring Platform` entry to the roadmap and retitle the remaining release gate `PHASE-14B`, reconciling the `ops` tables (`cost_meters` subsumed by `obs_ai_cost_budget`; `restore_validations` / `e2e_runs` stay with `PHASE-14B`). Update `error-handling-observability.md` §5 to the new stack + SLO list, correct the AI engineering standard's cost section (`latency_ms` -> `duration_ms`) and add eval detail, add the new env vars to the deployment plan, and register the plan in `CONTEXT.md`. Map each Appendix A hardening item to a ticket or a later phase.

Acceptance criteria (verbatim):

- [ ] Roadmap gains `PHASE-14A`; the release gate is retitled `PHASE-14B` with the `ops`-table reconciliation stated.
- [ ] `error-handling-observability.md` §5 and the AI standard A7 are updated; deployment plan lists the new env vars; `CONTEXT.md` registers the plan.
- [ ] Every Appendix A hardening item is mapped to a ticket or a later phase.
- [ ] `npm run lint` passes.

## Read-list (in order)

1. `docs/roadmap/implementation-roadmap.md` §2.14 Phase 14 - End-to-End Integration, Observability & Release Readiness (the section to carve; its schema-delta block lists the `ops` tables `cost_meters` / `restore_validations` / `e2e_runs` that the reconciliation re-distributes) and §3 End-to-End Traceability Matrix (read whole: §3.1 Feature -> Module -> Phase, §3.2 External Interface / Actor -> Phase, §3.3 Module Primary-Build-Phase Map). §3.1's `NFR-001` row cites `ops` - `cost_meters` and needs the subsumption wording; §3.3 needs a `MOD-013` row with its primary build phase. These matrices are the single source of truth for phase/feature/module edges - do not invent edges, register changes here. (~4.4K)
2. `docs/plans/plan-phase14-observability.md` §14 Docs & ADR changes (the canonical change list this ticket executes) and Appendix A - Carried-forward hardening (A.1 Prioritised table, A.3 Ship-now detail, A.4 Later detail) - the twelve hardening items, each carrying its Batch-1 ticket id (A1/A3/A4), Batch-2 bucket, or `PHASE-14B`/later home; the roadmap entry must map every one. (~1.3K)
3. `docs/standards/error-handling-observability.md` §5 Metrics & Alerts (cost-aware) - replace the generic "free/self-hosted options" guidance with the new stack (structlog JSON, Sentry, OTel + Grafana Cloud, Langfuse, Postgres `observability` as system of record) and fold in the plan §11 SLO list (auth `validate_token` p95 < 100 ms, `verify_otp` p95 < 400 ms, directory search p95 < 250 ms, AI call p95 <= 30 s, care-loop latency, error rate < 1%) and the alert set (audit tamper, backup failure, AI budget meter > 80%, outbox backlog, circuit-breaker open, dead-letter row, provider-health drop), keeping the "no PHI in alert payloads" line. (~0.1K)
4. `docs/standards/ai-engineering-standards.md` A7 Observability & Tracing - fix the trace-captures list field `latency_ms` -> `duration_ms` (matches plan §6 span metadata and the real `intake_ai_jobs` column) and add the eval detail (Langfuse datasets, LLM-as-judge for completeness/confidence-calibration/rx-draft accuracy, annotation queue fed by doctor review outcomes - plan §1 goal 7 and §13 Batch 2). (~0.3K)
5. `docs/plans/deployment-plan/portfolio-deployment-plan.md` §4.1 `apps/backend/app/config.py` (the Settings/env-var documentation idiom) and §5.2 Render (backend) item 4 env-var table - the table the new gates join: `LOG_FORMAT`, `SENTRY_DSN` / `SENTRY_TRACES_SAMPLE_RATE`, `OTEL_ENABLED` / `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_EXPORTER_OTLP_HEADERS` / `OTEL_TRACES_SAMPLER_RATIO` / `OTEL_SERVICE_VERSION`, `METRICS_ENABLED`, `OBSERVABILITY_ENABLED` (plan §4 gate names; `sync: false` for anything secret). Leave the existing `DEMO_MODE` / `CORS_ALLOWED_ORIGINS` rows untouched. (~0.8K)
6. `CONTEXT.md` - the `## Doc inventory` table needs a row registering `docs/plans/plan-phase14-observability.md` the way earlier plan docs are registered, and the glossary should gain a term only if the new ADRs introduce one (e.g. `MOD-013` / `observability` schema). Read the doc-inventory table and the `## Build-session protocol` / `## Cross-reference rule` sections; skip the full glossary. (~1.2K)

## Do NOT read

- `docs/architecture/internal-modules.md` MOD specs and §4.1/§4.2/§5 matrices - that is D2's file. D2 registers the MOD-013 event subscriptions there; D3 must not invent event names.
- The new observability ADRs - those are D1's output; D3 cites them in `CONTEXT.md` at most.
- `docs/archive/` and all source code.

## Baseline verify (must pass before the first edit)

- `npm run lint` (pre-commit --all-files) - the docs-only gate. It auto-reformats (prettier --write on `.md`, ruff --fix) and includes the `check-em-dashes` and `check-event-names` local hooks, so run it before the first edit and again as done-verify. (The brief author did not run it: research-only session, and pre-commit writes files. `git status` today is not clean - do not treat pre-existing `M`/`??` entries as yours.)

## Done-verify (acceptance criteria -> commands)

- `npm run lint` - green (no em-dashes anywhere - simple dashes only).
- Grep gate: `implementation-roadmap.md` gains a `PHASE-14A` entry and the release gate is titled `PHASE-14B` with the `ops`-table reconciliation stated; the `NFR-001` §3.1 row no longer credits `ops` - `cost_meters`.
- Grep gate: `error-handling-observability.md` §5 names the new stack and the SLO set; `ai-engineering-standards.md` A7 says `duration_ms` and describes the eval framework.
- Grep gate: the deployment-plan env table lists every new observability gate; `CONTEXT.md` Doc inventory references `docs/plans/plan-phase14-observability.md`.
- Appendix A sweep: each of the twelve hardening items carries a Batch-1 ticket id, Batch 2, or `PHASE-14B`/later phase - nothing left with an empty home.
- No edits outside the four files named in Scope.

## Handoff notes

- Sibling boundaries: D1 (#711) owns `docs/adr/*` and `docs/architecture/system-context.md`; D2 (#713) owns the `internal-modules.md` MOD-013 spec and its §4.1/§4.2/§5 rows. D3 owns exactly the roadmap, the two standards files, the deployment plan, and `CONTEXT.md`.
- D3 is blocked by D1 (the ADRs are what D3 registers in CONTEXT). D2 is likewise blocked by D1 only.
- The roadmap `PHASE-14A` entry should mirror the plan's §12 Batch-1 ticket list (A1-E) as its scope, and `PHASE-14B` keeps the plan §1 "Does NOT cover" carve-out: the full-loop E2E suite and the launch/restore release gate cannot run until Phases 9-13 exist. State the `ops`-table reconciliation explicitly (`cost_meters` subsumed by `obs_ai_cost_budget`; `restore_validations` / `e2e_runs` stay with `PHASE-14B`) rather than silently deleting rows.
- Prettier may rewrap markdown tables in all four files; the substantive edits are confined to the sections named in the read-list.
