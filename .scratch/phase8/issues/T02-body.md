## Parent

Part of #416

## What to build

The pure case lifecycle state machine, case-domain events, and registration of MOD-006 event constants in the shared event registry (`bus/events.py`).

**Case state machine** in `care/domain/state_machine.py`: states `PreSummary | PrescriptionPending | Closed`, actions `MARK_CONSULT_COMPLETE | CLOSE_WITHOUT_RX`. Transitions enforce finalized-pre-summary gate on handshake; `ConsultComplete` is an audited milestone from-to (not a dwell state); `CLOSE` is terminal and requires a close reason. A rejected draft must never auto-close the case.

**Event constants in `bus/events.py`:** follow the existing `EVENT_<DOMAIN>_<ACTION>` naming convention. Add:

- `EVENT_CASE_CONSULT_COMPLETE = "case.consult_complete"`
- `EVENT_CASE_CLOSED = "case.closed"`
- `EVENT_PRESCRIPTION_DRAFT_CREATED = "prescription.draft_created"`
- `EVENT_PRESCRIPTION_REVIEWED = "prescription.reviewed"`
- `EVENT_PRESCRIPTION_APPROVED = "prescription.approved"`
- `EVENT_PRESCRIPTION_REJECTED = "prescription.rejected"`
- `EVENT_PRESCRIPTION_ISSUED` already exists at line 25 - do NOT recreate.

**REGULATED_ACT_TYPES update:** promote the bare strings `"prescription.approved"` and `"prescription.rejected"` (lines 126-127) to the named constants. Add `EVENT_PRESCRIPTION_ISSUED` to the frozenset. `case.*`, `prescription.draft_created`, and `prescription.reviewed` are explicitly NOT regulated acts (events.py:117 comment - "case consult are skipped" from the hash chain). Only the three issuance/rejection events enter the audit chain.

**Case-domain event payloads** in `care/domain/events.py`: `CaseConsultCompletePayload`, `CaseClosedPayload` following the intake events Pydantic envelope pattern (no-PHI, only ids/lifecycle facts).

## Acceptance criteria

- [ ] Case state machine has exhaustive status x action matrix with `IllegalCareTransitionError` for illegal edges
- [ ] Consult-complete gate rejects when pre-summary is not finalized
- [ ] Close-without-RX is terminal and requires a reason
- [ ] All new MOD-006 event constants registered in `bus/events.py` using `EVENT_` prefix
- [ ] `prescription.approved`/`prescription.rejected` bare strings in REGULATED_ACT_TYPES promoted to constants; `EVENT_PRESCRIPTION_ISSUED` added to the frozenset
- [ ] `check_event_names.py` and `check_module_boundaries.py` tests pass
- [ ] Case machine pure tests pass: `pytest tests/unit/test_care_case_state_machine.py`

## Blocked by

- #417 (T01 Care Schema Migration & DTO Models)
- #425 (T00 Glossary & CONTEXT.md - naming authority)

## Context pack

- **Read-list:** `CONTEXT.md` glossary "Consultation orchestration & e-prescription" section (from T00 - use these exact term names), `apps/backend/modules/intake/domain/state_machine.py` (reference pattern: enum/transition/error), `apps/backend/modules/intake/domain/events.py` (event payload pattern), `apps/backend/bus/events.py` (current registry, `EVENT_` prefix convention, `REGULATED_ACT_TYPES` scope), `apps/backend/modules/care/domain/exceptions.py` (current scaffold), `docs/architecture/internal-modules.md` section 3.6 (case machine states and transitions)
- **Do NOT read:** facade.py, routes, intake facade, test files, prototype HTML, prescription domain (separate ticket)
- **Baseline verify:** `npm run lint && npm run typecheck`
- **Done-verify:** `python -m pytest tests/unit/test_care_case_state_machine.py -v && python -m pytest tests/unit/test_event_names.py tests/unit/test_check_module_boundaries.py -v`
- **Brief file:** `docs/agents/briefs/PHASE-8-T02-case-domain.md`
