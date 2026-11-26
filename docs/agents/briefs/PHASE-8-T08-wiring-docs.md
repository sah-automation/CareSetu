# Brief - T08 Cross-Module Wiring & Documentation

**Ticket:** #424 · **Parent:** #416 · **Refreshed:** 2026-09-14 (re-cut: seams moved to T04/T05; PRD + internal-modules §3.6 + roadmap label fix added)
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

Cross-module event wiring, documentation updates, and final verification. **The intake-facade seams are NOT here - `get_finalized_pre_summary` lives in T04 (#420), `request_rx_draft` in T05 (#421).**

Subscribes to `pre_summary.ready`, `pre_summary.low_confidence`, `report.filed`. Updates `internal-modules.md` (§3.6 spec + §4.1 sync matrix + §4.2 registry), roadmap §2.8 (status + `v7.0__init_care.sql` -> `v8_0__init_care` label fix), PRD (§4.4 CFL-002/CFL-003 + legacy snake_case event names, §7.1 blocker rows, §5 traceability), and writes ADRs 0014/0015.

### Acceptance criteria

- [ ] Event subscriptions wired in `care/adapters/__init__.py` (pre_summary.ready, pre_summary.low_confidence, report.filed)
- [ ] `internal-modules.md` §3.6 refresh + §4.1/§4.2 updates complete
- [ ] Roadmap §2.8 status updated incl. `v7.0__init_care.sql` -> `v8_0__init_care` label fix
- [ ] PRD §4.4/§7.1/§5 annotate CFL-002/CFL-003 resolved; legacy snake_case event names corrected to dot-notation
- [ ] ADRs 0014 and 0015 written
- [ ] Full harness green: `npm run lint && npm run typecheck && npm run test:unit:backend && npm run migration-check && npm run scan`

## Read-list (in order)

1. `apps/backend/modules/care/adapters/__init__.py` - current scaffold with `register_handlers(registry)` (~0.2K tokens)
2. `apps/backend/modules/intake/adapters/__init__.py` - event subscription pattern: `registry.subscribe(EVENT, handler)`, handler signature (~0.5K tokens)
3. `apps/backend/bus/events.py` - final event registry after T02 (constants + REGULATED_ACT_TYPES) (~0.5K)
4. `CONTEXT.md` glossary "Consultation orchestration & e-prescription" section (T00 output) - the vocabulary the docs must use (~0.5K)
5. `docs/architecture/internal-modules.md` sections 3.6, 4.1, 4.2 - the specs/registry to refresh (~1.5K tokens)
6. `docs/roadmap/implementation-roadmap.md` section 2.8 (lines ~544-583) - Phase 8 status, migration label line ~566 (~0.8K tokens)
7. `docs/prd/project-prd.md` sections 4.4 (features 4.4.1/4.4.2), 7.1 (lines ~843-848), 5 traceability (lines ~885-886) (~1.5K tokens)
8. `docs/adr/` - any existing ADR for format reference (~0.5K tokens)

## Do NOT read

- Prototype HTML
- Test files (already written)
- Domain files (already implemented)
- Consent facade, health facade
- Intake facade (seams done in T04/T05)

## Baseline verify (must pass before the first edit)

- `npm run lint && npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `npm run lint && npm run typecheck && npm run test:unit:backend && npm run migration-check && npm run scan`

## Handoff notes

- Event subscriptions follow the intake adapter pattern: handler `async def _on_pre_summary_ready(payload)` calling the appropriate `CareFacade` method, registered via `registry.subscribe(EVENT_TYPE, handler)`.
- The migration label fix is mandated by issue #416 itself: "the roadmap's `v7.0__init_care.sql` label is stale".
- PRD §4.4 line ~397-399 uses legacy snake_case event names (`prescription_draft_created`, `prescription_approved`, `prescription_rejected`) - the registry grammar (`domain.action`) supersedes them repo-wide and `check_event_names.py` rejects the snake_case spelling. Correct them in line.
- PRD §7.1 lines ~847-848: strike the `CFL-002/RISK-EVAL-003` and `CFL-003/GAP-003` blocker rows, noting resolution via issue #416 Phase 8.
- ADR 0014 covers: revision-freeze guarantee, verification declaration requirement, `edited_yn` derivation, issuance immutability (no supersede/void).
- ADR 0015 covers: AI as drafting-assistant only, 3-attempt drafting cap, manual-authoring always-open fallback, gate-behind-seam compliance posture (CFL-002).
- T08 is blocked by T00 because the doc-delta pass must use the canonical vocabulary the glossary registers.
