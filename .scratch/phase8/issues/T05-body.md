## Parent

Part of #416

## What to build

The prescription half of `CareFacade` - AI-drafted and manual prescriptions through approval and issuance - PLUS the intake-facade seam it depends on.

**New seam (this ticket):** make `IntakeFacade.request_rx_draft` live. It is currently a declared contract stub raising `NotImplementedError` at `apps/backend/modules/intake/facade.py:769` with signature `(doctor_input_ref, pre_summary_ref, history_summary=None)`. Per issue #416, Phase 8 implements it. Scope: produce a structured rx draft from the doctor input via the existing intake AI gateway/pipeline seam (the Phase-7 providers - mock/fallback/openai-compatible), returning a typed result containing the draft `rx_items`; the `history_summary` parameter is the consent-gated history context. Keep it a first working version - the draft is stored by CareFacade as an immutable `draft_snapshot`.

**Consent-gated drafting context (NFR-SEC-006):** any use of the patient's record history for drafting goes through `HealthFacade.read_consented_history` (which calls `ConsentFacade.check_consent`), fail-closed. The `history_summary` passed to `request_rx_draft` is assembled from that consented read only.

**CareFacade methods** in `apps/backend/modules/care/facade.py`:

- `create_rx_draft(case_id, doctor_id, source, items=None)`: `source=ai_draft` calls `intake_facade.request_rx_draft` (consented history context), stores the immutable `draft_snapshot` jsonb, enforces drafting cap (max 3 attempts / 2 rejections). `source=manual` captures the doctor's `rx_items` directly. Returns `PrescriptionDetailView`.
- `save_rx_revision(case_id, rx_id, doctor_id, rx_items)`: writes the doctor's working revision to `care_rx_items`; the approved revision is this state, never the raw draft.
- `approve_prescription(case_id, rx_id, doctor_id, verification_declaration)`: requires `verification_declaration=True` (stored on `rx_approvals` with `declared_at`). Freezes the saved revision: sets `issued_at`, `attributed_doctor`, derives `edited_yn` vs `draft_snapshot`. Blocked if revision save failed or stale. Publishes `prescription.approved` + `prescription.issued`.
- `reject_prescription(case_id, rx_id, doctor_id, reason)`: requires non-empty reason; records on `rx_approvals`; publishes `prescription.rejected`; does NOT auto-close the case.
- `get_approved_prescription(rx_id)`: returns only approved+issued frozen prescriptions (Phase-10 source of truth).

All methods: same-transaction outbox writes, typed Pydantic returns, doctor attribution. The approval gate sits behind an interface seam so a stricter regulatory rule (CFL-002) can slot in without redesign.

## Acceptance criteria

- [ ] `IntakeFacade.request_rx_draft` is implemented (no longer raises NotImplementedError) and returns a typed draft
- [ ] AI draft stores immutable `draft_snapshot` and enforces cap (3rd draft blocked, manual still open)
- [ ] History read for drafting goes through consented path, fail-closed (NFR-SEC-006)
- [ ] `save_rx_revision` updates working revision; stale revision rejected
- [ ] `approve_prescription` requires verification declaration; freezes revision; derives `edited_yn`; approval gate behind a replaceable seam
- [ ] `reject_prescription` requires reason; does not auto-close case
- [ ] `get_approved_prescription` returns only issued prescriptions
- [ ] All methods write outbox in same transaction
- [ ] Facade unit tests pass: `pytest tests/unit/test_care_facade_rx.py`

## Blocked by

- #417 (T01 Care Schema Migration & DTO Models)
- #418 (T02 Case Domain)
- #419 (T03 Prescription Domain)
- #425 (T00 Glossary & CONTEXT.md - naming authority)

## Context pack

- **Read-list:** `CONTEXT.md` glossary (T00 section - `e-prescription`, `prescription source`, `draft snapshot`, `drafting cap`, `revision-freeze approval`, `verification declaration`, `edited_yn`), `apps/backend/modules/intake/facade.py` (the `request_rx_draft` stub at ~line 769 + the `begin()`/`write_outbox()` pattern), `apps/backend/modules/intake/adapters/ai_gateway.py` (the AI drafting seam), `apps/backend/modules/care/domain/prescription_machine.py` (T03 machine), `apps/backend/modules/care/schema/models.py` (rx tables), `apps/backend/modules/care/care_models.py` (T01 DTOs), `apps/backend/modules/care/facade.py` (T04's methods), `docs/architecture/internal-modules.md` section 3.6
- **Do NOT read:** routes, tests, prototype HTML, consent facade internals (only the `check_consent` contract via `HealthFacade.read_consented_history`)
- **Baseline verify:** `npm run lint && npm run typecheck`
- **Done-verify:** `python -m pytest tests/unit/test_care_facade_rx.py -v`
- **Brief file:** `docs/agents/briefs/PHASE-8-T05-carefacade-rx.md`
