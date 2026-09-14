# Brief - T05 CareFacade - Prescription Workflow

**Ticket:** #421 · **Parent:** #416 · **Refreshed:** 2026-09-14 (re-cut: added `request_rx_draft` seam + consented drafting context)
**Reading surface:** ~9K tokens (budget 10K) - within budget

## Scope

The prescription half of `CareFacade` PLUS the intake-facade seam it depends on.

**New seam (this ticket):** implement `IntakeFacade.request_rx_draft` - currently a contract stub raising `NotImplementedError` (facade.py ~line 769), signature `(doctor_input_ref, pre_summary_ref, history_summary=None)`. Per issue #416, Phase 8 makes it live: produce a structured rx draft from the doctor input via the existing intake AI gateway/pipeline seam, return a typed result with the draft `rx_items`. The `history_summary` is assembled from the consent-gated history read. This ticket no longer lives in T08.

Methods: `create_rx_draft`, `save_rx_revision`, `approve_prescription`, `reject_prescription`, `get_approved_prescription`. All same-transaction outbox writes, typed Pydantic returns, doctor attribution. Approval gate sits behind a replaceable seam (CFL-002).

### Acceptance criteria

- [ ] `IntakeFacade.request_rx_draft` is implemented (no longer raises NotImplementedError) and returns a typed draft
- [ ] AI draft stores immutable `draft_snapshot` and enforces cap (3rd draft blocked, manual still open)
- [ ] History read for drafting goes through consented path, fail-closed (NFR-SEC-006)
- [ ] `save_rx_revision` updates working revision; stale revision rejected
- [ ] `approve_prescription` requires verification declaration; freezes revision; derives `edited_yn`; gate behind replaceable seam
- [ ] `reject_prescription` requires reason; does not auto-close case
- [ ] `get_approved_prescription` returns only issued prescriptions
- [ ] All methods write outbox in same transaction
- [ ] Facade unit tests pass

## Read-list (in order)

1. `CONTEXT.md` glossary "Consultation orchestration & e-prescription" section (T00 output) - canonical `e-prescription`, `prescription source`, `draft snapshot`, `drafting cap`, `revision-freeze approval`, `verification declaration`, `edited_yn`, `doctor input` (~0.5K)
2. `apps/backend/modules/intake/facade.py` - the `request_rx_draft` stub (~line 769) + the `begin()`/`write_outbox()` pattern / typed returns (~1.5K - targeted, skip the rest)
3. `apps/backend/modules/intake/adapters/ai_gateway.py` - the AI drafting seam the seam delegates to; provider mock/fallback for the first working version (~1K)
4. `apps/backend/modules/care/facade.py` - current scaffold + ticket 04's consultation methods (~1K tokens)
5. `apps/backend/modules/care/domain/prescription_machine.py` or `state_machine.py` - prescription machine from ticket 03: `RxStatus`, `RxAction`, `transition()` (~0.8K tokens)
6. `apps/backend/modules/care/schema/models.py` - `care_prescriptions`, `care_rx_items`, `care_rx_approvals` column names (~0.5K tokens)
7. `apps/backend/modules/care/care_models.py` - DTOs: `PrescriptionDetailView`, `RxItemView` (~0.5K tokens)
8. `docs/architecture/internal-modules.md` section 3.6 (lines 343-368) - revision-freeze, verification declaration, drafting cap, `edited_yn` spec (~0.5K tokens)

## Do NOT read

- Intake facade beyond the stub/pattern (already read in ticket 04)
- Routes, tests, prototype HTML
- Consent facade internals - only the `check_consent` contract via `HealthFacade.read_consented_history`
- Case domain (separate ticket)

## Baseline verify (must pass before the first edit)

- `npm run lint && npm run typecheck`

## Done-verify (acceptance criteria -> commands)

- `python -m pytest tests/unit/test_care_facade_rx.py -v`

## Handoff notes

- `create_rx_draft` with `source=ai_draft` stores the AI output as immutable `draft_snapshot` JSONB on `care_prescriptions`; `attempt_no` increments per AI draft on the same case. `source=manual` has no snapshot.
- `request_rx_draft` first working version: delegate to the existing intake AI gateway/pipeline seam (the Phase-7 providers). The `history_summary` param is assembled ONLY from `HealthFacade.read_consented_history` (fail-closed) - never from a raw history read.
- `save_rx_revision` writes to `care_rx_items` (delete + re-insert pattern for the working revision). The revision is what gets approved.
- `approve_prescription` freezes by: reading the current `care_rx_items`, comparing against `draft_snapshot` to derive `edited_yn`, setting `issued_at = now()`, `attributed_doctor = doctor_id`, `status = ApprovedIssued`. If items cannot be read, approval is blocked. The verification-declaration gate lives behind an interface so a stricter regulatory rule (CFL-002) can slot in.
- `reject_prescription` sets `status = Rejected`, records rejection on `care_rx_approvals` with reason. Does NOT touch `care_cases.stage`.
- `get_approved_prescription(rx_id)` filters: `status = ApprovedIssued AND issued_at IS NOT NULL`. This is the Phase-10 read path.
