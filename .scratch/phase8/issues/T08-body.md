## Parent

Part of #416

## What to build

Cross-module event wiring, documentation updates, and final integration verification. **The intake-facade seam implementations (`get_finalized_pre_summary`, `request_rx_draft`) are NOT here anymore - they moved to T04 (#420) and T05 (#421) respectively.**

**Event subscriptions** in `care/adapters/__init__.py`: subscribe to `pre_summary.ready` (attach finalized summary to case / spawn the case), `pre_summary.low_confidence` (forced-review flag before handshake), `report.filed` (attach to case context, Phase 9). Follow the intake adapter pattern: handler functions calling `CareFacade` methods, registered via `registry.subscribe(EVENT, handler)`.

**Documentation updates:**

1. **`docs/architecture/internal-modules.md`**:
   - §3.6 MOD-006 spec (lines 340-375): refresh to the built reality - real table names, real facade method signatures, actual events, the verification declaration + revision-freeze that resolve CFL-002
   - §4.1 sync matrix: add `get_finalized_pre_summary` and `request_rx_draft` rows for the MOD-005/MOD-006 edge
   - §4.2 event registry: register `case.closed`, `prescription.draft_created`, `prescription.reviewed`, `prescription.issued`; show `case.consult_complete`, `prescription.approved`/`rejected` promoted to constants
2. **`docs/roadmap/implementation-roadmap.md`**:
   - §2.8 Phase 8 status: mark MOD-006 case+rx lifecycle and approval gate Delivered; mark CFL-002/CFL-003 baselines Resolved (records the risk-matrix resolution)
   - Line ~566: fix the stale migration label `v7.0__init_care.sql` -> `v8_0__init_care` (issue #416 explicitly calls this label stale)
3. **`docs/prd/project-prd.md`**:
   - §4.4.1 Rule 2 (`CFL-003` line ~360): annotate doctor-initiated baseline resolved
   - §4.4.2 Rule 2 (`CFL-002`/`RISK-EVAL-003` line ~392): annotate baseline posture resolved by the approval gate seam
   - §4.4 event-out contract (lines ~397-399): correct the legacy snake_case event names `prescription_draft_created`/`prescription_approved`/`prescription_rejected` to the dot-notation registry `prescription.draft_created`/`prescription.approved`/`prescription.rejected` (registry grammar is enforced repo-wide)
   - §7.1 Blockers & Open Items (lines ~847-848): strike or annotate the CFL-002/RISK-EVAL-003 and CFL-003 rows
   - §5 traceability table (lines ~885-886): FEAT-008/FEAT-009 status `Baseline Approved (open decision)` -> `Baseline Approved (resolved in Phase 8)`
4. **ADR `0014-issued-prescription-approval-contract.md`**: revision-freeze guarantee, verification declaration, `edited_yn` derivation, issuance immutability
5. **ADR `0015-ai-assisted-drafting-posture.md`**: AI as drafting-assistant only, 3-attempt cap, manual-authoring always-open fallback, compliance posture resolving RISK-EVAL-003/CFL-002

**Final verification:** full harness green.

## Acceptance criteria

- [ ] Event subscriptions wired in `care/adapters/__init__.py` (pre_summary.ready, pre_summary.low_confidence, report.filed)
- [ ] `internal-modules.md` §3.6 refresh + §4.1/§4.2 updates complete
- [ ] Roadmap §2.8 status updated incl. `v7.0__init_care.sql` -> `v8_0__init_care` label fix
- [ ] PRD §4.4/§7.1/§5 annotate CFL-002/CFL-003 resolved; legacy snake_case event names corrected
- [ ] ADRs 0014 and 0015 written
- [ ] `npm run lint && npm run typecheck && npm run test:unit:backend && npm run migration-check && npm run scan` all pass

## Blocked by

- #422 (T06 Doctor Routes & RBAC)
- #423 (T07 Unit Tests)
- #425 (T00 Glossary & CONTEXT.md - so the doc-delta pass sees the canonical vocabulary)

## Context pack

- **Read-list:** `apps/backend/modules/care/adapters/__init__.py` (current scaffold), `apps/backend/modules/intake/adapters/__init__.py` (subscription pattern), `bus/events.py` (final registry after T02), `docs/architecture/internal-modules.md` sections 3.6/4.1/4.2, `docs/roadmap/implementation-roadmap.md` section 2.8, `docs/prd/project-prd.md` sections 4.4/7.1/5, `docs/adr/` (existing ADRs for format), CONTEXT.md glossary (T00 output)
- **Do NOT read:** prototype HTML, test files, domain files (already implemented), consent facade
- **Baseline verify:** `npm run lint && npm run typecheck`
- **Done-verify:** `npm run lint && npm run typecheck && npm run test:unit:backend && npm run migration-check && npm run scan`
- **Brief file:** `docs/agents/briefs/PHASE-8-T08-wiring-docs.md`
