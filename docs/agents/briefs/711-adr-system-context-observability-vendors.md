# Brief - 711 D1 - ADRs + system-context observability vendors

**Ticket:** #711 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~8K tokens (budget 10K) - within budget

## Scope

Record the resolved decisions and external surface for the observability stack. Add three ADRs: (1) observability topology + free-tier vendor choices; (2) MOD-013 and its `observability` schema registration as a one-schema-rule extension of the audit pattern; (3) OpenTelemetry adoption. Add observability vendor entries (`EXT-005` Langfuse, `EXT-006` Grafana Cloud, `EXT-007` Sentry) to `system-context.md`, including their off-by-default gating and PHI-free posture.

Acceptance criteria (verbatim):

- [ ] Three ADRs added under `docs/adr/` following the repo's ADR format, each citing the plan.
- [ ] `system-context.md` gains the three observability vendor entries with their gates and boundary rules.
- [ ] No cross-schema or PHI rule contradicted.
- [ ] `npm run lint` passes.

## Read-list (in order)

1. `docs/adr/0002-transactional-outbox-as-async-seam.md` then `docs/adr/0017-professional-prescription-record-cards.md` - the repo ADR anatomy: `# ADR-NNNN: <title>` header, `Status` / `Date` / `Decides` / `Traceability` (+ optional `Evidence`), then `Context`, `Decision` (with `D1/D2/...` subheadings where the decision subdivides), `Considered options`, `Consequences`. Copy this shape exactly; each new ADR's Traceability line must cite `plan-phase14-observability.md` and the batch tickets. (~2K)
2. `docs/architecture/system-context.md` §3 External Actors Catalog, §4 External Systems & Third-Party Integration Matrix (§4.1 Integration Catalog + §4.2 Integration Specifications), §5 Non-Functional Boundary Rules & Edge Protection - the exact homes for the three new vendor entries: one `EXT-005`/`EXT-006`/`EXT-007` catalog row in §4.1 plus a detached concrete-contract block in §4.2 in the style of the `EXT-001`..`EXT-004` contracts (direction, protocol, payload, error/retry, security). The off-by-default gates (`LANGFUSE_PUBLIC_KEY` present-but-no-op, `SENTRY_DSN` empty = off, `OTEL_ENABLED` off, `OBSERVABILITY_ENABLED` off - plan §4) and the PHI-free posture must not contradict §5.1: `NFR-001` cost floor (free tiers only), `NFR-SEC-006` consent-gated minimal PHI egress (pseudonymous ids only in telemetry), `NFR-PERF-003` external-call timeouts. (~4K)
3. `docs/plans/plan-phase14-observability.md` §3 Target architecture (topology + vendor data flow), §4 Pillars & wiring (the per-vendor gate table), §7.1 New module `MOD-013 Observability` (the exact one-schema-rule extension of the audit pattern that ADR 2 records), §10 Security & Guardrails and PHI (redaction postures the vendor entries promise: structlog processor, Sentry `before_send`, OTel attribute allow-list), §14 Docs & ADR changes (the canonical change list the acceptance criteria mirror), §15 Risks (what each ADR's Consequences must pre-empt: free-tier ceilings, PHI leakage, Render spin-down flush). (~1.5K)

## Do NOT read

- `docs/architecture/internal-modules.md` MOD specs and §4.1/§4.2/§5 matrices - that is D2's file.
- `docs/roadmap/implementation-roadmap.md`, the two standards docs, the deployment plan, or any source code - those are D3's or the build tickets' surface.
- `docs/archive/`.

## Baseline verify (must pass before the first edit)

- `npm run lint` (pre-commit --all-files) - the docs-only gate. It auto-reformats (prettier --write on `.md`, ruff --fix) and includes the `check-em-dashes` and `check-event-names` local hooks, so run it before the first edit and again as done-verify; review whatever it reformats. (The brief author did not run it: research-only session, and pre-commit writes files. `git status` today is not clean - do not treat pre-existing `M`/`??` entries as yours.)

## Done-verify (acceptance criteria -> commands)

- `npm run lint` - green (includes the no-em-dash hook - use simple dashes, never em-dashes, in every new file).
- Grep gate: `docs/adr/` contains exactly three new ADRs, each citing `plan-phase14-observability.md`.
- Grep gate: `system-context.md` §4.1 contains `EXT-005` (Langfuse), `EXT-006` (Grafana Cloud), `EXT-007` (Sentry) rows carrying their off-by-default gates and PHI-free boundary language, with matching §4.2 contract blocks.
- Nothing written outside `docs/adr/` and `docs/architecture/system-context.md`.

## Handoff notes

- Sibling boundaries in the D re-cut: D3 (#714) owns the roadmap, the two standards docs, the deployment plan, and `CONTEXT.md`. D2 (#713) owns the `internal-modules.md` MOD-013 spec and its §4.1/§4.2/§5 rows. D1 owns ONLY the three ADRs and the `system-context.md` vendor entries.
- D1 is unblocked (start immediately) and D2/D3 are blocked by D1's ADRs - write ADR (2) early so the MOD-013 spec can cite it.
- Do not alter the `EXT-001..004` catalog rows or their §4.2 contracts. The observability vendors do not replace the LLM AI provider `EXT-002` (that stays the domain egress system of record; Langfuse observes it, it does not replace it) - state the separation in ADR (1) to prevent later merge churn.
- Table rows added to §4.1/§4.2 use the same column sets as the existing entries; keep the §3 actor catalog (`ACT-001..005`) untouched.
