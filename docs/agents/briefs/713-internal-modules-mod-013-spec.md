# Brief - 713 D2a - internal-modules MOD-013 module spec

**Ticket:** #713 · **Parent:** #692 · **Refreshed:** 2026-10-12
**Reading surface:** ~3K tokens (budget 10K) - within budget

## Scope

Add the **MOD-013 Observability** spec section to `docs/architecture/internal-modules.md`, as a sibling of the MOD-011 Audit spec. It must state: MOD-013 owns a private `observability` schema, consumes existing outbox events into that schema, exposes a read-only facade plus operator HTTP surfaces, and is telemetry - not a domain bounded context; aggregation never crosses schemas; no PHI in telemetry. Keep the matrices (`§4.1`/`§4.2`/`§5`) out of scope here - those are the sibling ticket.

### Acceptance criteria (verbatim from the ticket)

- [ ] MOD-013 spec section added mirroring MOD-011's structure (purpose, schema, events consumed, facade/surfaces, isolation + PHI rules).
- [ ] No cross-schema edge is invented; only outbox-event subscriptions are described.
- [ ] `npm run lint` passes.

## Read-list (in order)

1. This ticket's dossier (`d2a.md`) - the exact spec content to state: private `observability` schema; consumes existing outbox events into that schema; read-only facade plus operator HTTP surfaces; telemetry - not a domain bounded context; aggregation never crosses schemas; no PHI in telemetry (~0.3K tokens).
2. `CONTEXT.md` - build-session protocol, the cross-reference rule (edges get registered in the matrices, not drafted here), and the glossary terms `outbox`, `dispatcher`, `event bus`, `idempotent subscriber`, `module isolation rule` that the spec's phrasing must use verbatim (~0.6K tokens).
3. `internal-modules.md` §1 module-layout preamble - the decomposition strategy the spec must not contradict: one private PostgreSQL schema per module, CI-enforced isolation (no cross-schema imports / no cross-schema FKs), facade.py = sync seam and outbox events = async seam as the only legal cross-module edges, PHI-minimisation + consent-gating NFR line (~0.6K tokens).
4. `internal-modules.md` §3.11 `MOD-011` Audit spec, whole - the exact five-point structure to mirror: Module ID / Primary Scope / Traceability Link, then `#### 1. Data Ownership & Storage Isolation`, `#### 2. Inbound & Outbound Interfaces` (inbound sync APIs / inbound events subscribed / outbound events published), `#### 3. Core Business Logic & State Machines`, `#### 4. High-Level Tech Stack & Framework Constraints`, `#### 5. Module NFR Allocation`. MOD-013 is defined in plan §7.1 as a "one-schema-rule extension of the audit pattern" - this block is the shape to copy (~0.5K tokens).
5. Plan `docs/plans/plan-phase14-observability.md` §7 (§7.1 module, §7.2 schema, §7.3 event consumer) - the authoritative MOD-013 facts the spec states: sibling of MOD-011 (the twelfth `MODULE_SCHEMAS` entry and `v9_0__init_observability` are B3 #701's build concern - the spec records ownership, not code); the six tables `obs_ai_usage_daily`, `obs_ai_cost_budget`, `obs_ai_provider_health`, `obs_business_daily`, `obs_alert_events`, `obs_consumed_events`; the consumer's subscription list (`ai_job.completed`, `ai_job.failed`, `case.*`, `partner.*`, `consent.*`, `record.accessed`, `audit.*`); the `event_id` idempotency-ledger rule; and the narrow read-only exception instead of cross-schema reads (~0.5K tokens).

## Do NOT read

- The `§4.1` sync matrix, `§4.2` event registry, and `§5` traceability in `internal-modules.md` - that is the sibling ticket D2b (#715). This spec only _names_ the events it consumes; it does not register rows.
- `docs/architecture/system-context.md` and the observability ADRs - D1's output (#711). Cite the new ADR; do not draft it.
- `docs/roadmap/implementation-roadmap.md`, `docs/standards/*`, the deployment plan, `CONTEXT.md` edits - D3's surface (#714).
- The other module specs (§3.1-§3.10), the §2 diagrams, and §6 checklist.
- `docs/archive/`, the PRD, and all source code.

## Baseline verify (must pass before the first edit)

- `npm run lint` (pre-commit --all-files) on the untouched tree - the docs-only gate. It auto-reformats (prettier --write on `.md`, ruff --fix) and includes the `check-em-dashes` (use simple dashes, never em-dashes) and `check-event-names` local hooks, so run it before the first edit and again as done-verify; review whatever it reformats. `git status` today is not clean - do not treat pre-existing `M`/`??` entries as yours. (The brief author did not run it: research-only session.)

## Done-verify (acceptance criteria - commands)

- `npm run lint` - green.
- Grep gate: `internal-modules.md` §3 gains a `MOD-013 Observability` spec block stating: private `observability` schema; consumes existing outbox events into that schema; read-only facade plus operator HTTP surfaces; telemetry - not a domain bounded context; aggregation never crosses schemas; no PHI in telemetry.
- Grep gate: the spec's Inbound Events Subscribed line names only events already present in the §4.2 registry (`ai_job.completed`, `ai_job.failed`, `case.*`, `partner.*`, `consent.*`, `record.accessed`, `audit.*`) - nothing invented.
- No edit lands in the `§4.1`/`§4.2`/`§5` matrices, and nothing outside `docs/architecture/internal-modules.md` is written.

## Handoff notes

- Sibling boundaries in the D re-cut: D1 (#711) owns the three ADRs and the `system-context.md` vendor entries; D2b (#715) owns the §4.1/§4.2/§5 matrix rows; D3 (#714) owns the roadmap, the two standards docs, the deployment plan, and `CONTEXT.md`. This ticket owns ONLY the MOD-013 spec block in `internal-modules.md`.
- Blocked by #711 (ADRs + vendor entries) so the spec can cite the ADR. Cite the ADR that records the MOD-013/`observability` one-schema registration the way §3.12/§3.13 cite ADR-0019/0020, keeping the citation on the plan §14 ADR (D1's second ADR) rather than inventing a number; if it has not landed when this runs, cite it by topic.
- Placement: spec sections run `MOD-001`..`MOD-012` plus the §3.13 profile-media adapter; append MOD-013 as the next `### 3.x` block after §3.13, keeping the `---` separator convention. Insertion-by-delivery (as MOD-012/§3.13 were) reads better than renumbering after MOD-011.
- The §4.1 sync row(s) for the operator HTTP facade, the §4.2 subscription rows, and the §5 traceability rows are #715's work - do not pre-claim them even though the spec states the facts they will register.
- Build-brief heads-up (#701): the plan names the aggregates `obs_*`, but the module-boundary gate requires an `observability_` table prefix and the shared harness hardcodes the ledger as `consumed_events` (not `obs_consumed_events`). If the build resolves these, mirror the settled names; until then write the Data Ownership section from plan §7.2 so the spec and the later matrix registration agree.
