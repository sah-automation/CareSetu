## Parent

Part of #416

## What to build

The consultation half of `CareFacade` - case lifecycle from finalized pre-summary through consult-complete milestone to case closure - PLUS the intake-facade seam it depends on.

**New seam on `IntakeFacade`:** implement `get_finalized_pre_summary(...)` (does not exist today - grep confirms). Queries `intake_pre_summaries` and returns ONLY a `final`-state summary (the Phase-7 three-state `draft|reviewed|final`); raises if the summary is missing or not yet `final`. This is the handshake gate's data source and per issue #416 Further Notes must be confirmed before wiring `mark_consult_complete`.

**CareFacade methods** in `apps/backend/modules/care/facade.py`:

- `mark_consult_complete(doctor_id, case_id)`: gates on `intake_facade.get_finalized_pre_summary`, transitions case `PreSummary -> PrescriptionPending`, records `ConsultComplete` milestone (timestamp + doctor attribution), publishes `case.consult_complete` via `care_outbox` in the same transaction (ADR-0002).
- `get_case(doctor_id, case_id)`: case detail with stage, patient summary, pre-summary status. Doctor must own the case.
- `list_doctor_cases(doctor_id)`: open cases oldest-first, stage chips, non-closed only.
- `submit_doctor_input(case_id, input_type, media_ref, sensitive_class)`: records voice note or photo input; validates case state.

Constructor: `engine: AsyncEngine` + injected `intake_facade` (TYPE_CHECKING import to avoid circular deps). All methods: same-transaction outbox writes, typed Pydantic returns from the T01 DTOs, `partner_id` attribution.

## Acceptance criteria

- [ ] `IntakeFacade.get_finalized_pre_summary` returns only `final` summaries and raises otherwise
- [ ] `mark_consult_complete` rejects when pre-summary is not finalized (calls the new seam)
- [ ] `mark_consult_complete` transitions case to PrescriptionPending and publishes `case.consult_complete`
- [ ] `get_case` returns typed `CaseDetailView`; `list_doctor_cases` returns only open cases
- [ ] `submit_doctor_input` records input and validates case state
- [ ] All methods write outbox in same transaction as the domain write
- [ ] Facade unit tests pass with faked engine: `pytest tests/unit/test_care_facade_consult.py`

## Blocked by

- #417 (T01 Care Schema Migration & DTO Models)
- #418 (T02 Case Domain)
- #425 (T00 Glossary & CONTEXT.md - naming authority)

## Context pack

- **Read-list:** `CONTEXT.md` glossary (T00 section - `care case`, `case stage`, `consult complete milestone`, `finalized pre-summary`, `doctor input`), `apps/backend/modules/intake/facade.py` (constructor, `begin()` transaction, `write_outbox()` pattern; grep `request_rx_draft` skeleton for the seam near it), `apps/backend/modules/care/facade.py` (current scaffold), `apps/backend/modules/care/schema/models.py` (table columns), `apps/backend/modules/care/domain/state_machine.py` (T02's case machine), `apps/backend/modules/care/care_models.py` (T01 DTOs), `apps/backend/modules/care/outbox.py`, `docs/architecture/internal-modules.md` section 3.6
- **Do NOT read:** prescription domain, routes, consent facade, partner facade (grep `resolve_partner` signature only), prototype HTML
- **Baseline verify:** `npm run lint && npm run typecheck`
- **Done-verify:** `python -m pytest tests/unit/test_care_facade_consult.py -v`
- **Brief file:** `docs/agents/briefs/PHASE-8-T04-carefacade-consult.md`
