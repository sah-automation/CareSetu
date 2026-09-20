## Problem Statement

A patient and a licensed doctor consult off-platform. Today the platform can produce a finalized pre-summary (Phase 7), but there is no way to close that consult into the on-platform flow, and no way to issue an e-prescription at all. When the doctor wants to prescribe, the only option is the phone or paper - the care loop breaks, the patient's record gets no prescription, and Phase 10 (pharmacy fulfillment) has nothing to route.

The regulatory stakes are the highest of any slice: `RISK-EVAL-003` (AI-drafted prescription regulatory exposure) is flagged high and its compliance decision `CFL-002` is still open. The baseline is that AI drafts under the licensed doctor's authority, but that baseline is only safe if the platform structurally cannot issue a prescription the doctor did not review, verify, and approve - and if an AI outage can never strand a patient without a prescription.

## Solution

Build `MOD-006` (Care Case & E-Prescription, `care` schema) so that one care case per visit carries the handshake and the prescription lineage:

- A care case is born when its pre-summary is finalized; the doctor closes the off-platform consult on-platform in one action (consult complete milestone, case moves to prescription pending, patient notified once).
- The prescription lifecycle runs draft → doctor-reviewed revision → approved & issued → fulfilled, with a rejection branch. The AI produces a draft; the doctor corrects it or types it by hand; approval freezes **exactly the doctor's saved revision** - never the raw draft - so a lost edit cannot silently issue wrong medicine.
- Approval requires the doctor's verification declaration (a mandatory double-check checkbox), is timestamped and attributed, and issued prescriptions are immutable (corrections require a fresh visit).
- An AI draft is a drafting-assistant artifact only: capped at 3 attempts per case (2 rejections), and the doctor can always author a prescription manually, so AI failure or regulatory tightening never holds a visit hostage.

Resolves the open baselines `CFL-002`/`RISK-EVAL-003` and `CFL-003`; publishes `prescription.approved` for downstream phases (fulfillment, notifications, audits).

## User Stories

1. As a doctor, I want a care case opened for my patient once the AI pre-summary is finalized, so that the platform already knows which visit I am closing.
2. As a doctor, I want to be blocked from closing a consult when there is no finalized pre-summary, so that a prescription-stage case can never come from an unreviewed summary.
3. As a doctor, I want to close an off-platform consult on-platform in one action, so that the consult-complete milestone is recorded and the case moves straight to prescription pending.
4. As a patient, I want to be notified once when my doctor closes the consult, so that I know my prescription is being prepared without being spammed at every internal step.
5. As a doctor, I want my pending-cases list to show only open visits, so that I never re-open a closed case.
6. As a doctor, I want to submit a voice note or photo as prescribing input and have the AI draft a prescription from it, so that issuing a precise e-prescription is fast.
7. As a doctor, I want my draft attempts capped at three (two rejections), so that a stubborn AI draft cannot spin forever.
8. As a doctor, I want to edit any part of an AI draft before approving, so that the issued prescription reflects my clinical judgement, not the AI's.
9. As a doctor, I want my corrections to be saved to the platform before any approval, so that approving can only ever issue what I actually reviewed.
10. As a doctor, I want to see my edits recorded as a flag when they differ from the AI draft, so that the audit trail shows exactly how the issued prescription came to be.
11. As a doctor, I want to approve an unchanged AI draft in a single step without being forced to re-edit, so that a correct draft is not slowed down.
12. As a doctor, I want a mandatory checkbox I must tick before approving to confirm I have double-checked the prescription, so that no prescription is issued without my explicit verified review.
13. As a doctor, I want approval to issue the prescription timestamped and attributed to me, so that regulatory and audit questions always point at a specific doctor.
14. As a doctor, I want to reject a draft with a required reason, so that the no-path is recorded and the draft does not linger.
15. As a doctor, I want rejection to leave me free to retry with a fresh AI draft (up to the cap) or hand-type, so that one bad AI draft never strands a patient.
16. As a doctor, I want to write a prescription from scratch with no AI involved, so that an AI outage or a simple preference never blocks care.
17. As a doctor, I want the system to record whether a prescription came from an AI draft or from my manual authoring, so that the audit trail stays honest about AI involvement.
18. As a doctor, I want to close a visit without a prescription when no medicine is needed, so that the visit ends cleanly and leaves my pending list.
19. As a doctor, I want a rejected draft not to auto-close the visit, so that closing-without-prescription stays my deliberate decision.
20. As a chemist (Phase 10 forward), I want `get_approved_prescription` to serve only approved, frozen revisions, so that fulfillment can never act on a draft.
21. As a patient, I want my issued prescription to be immutable, so that what I receive is exactly what my doctor approved.
22. As a compliance reviewer, I want every issuance and rejection audited with actor, timestamp, decision, and reason, so that `REQ-023` is demonstrably met.
23. As a downstream consumer (fulfillment, notifications, audit), I want `prescription.approved` / `prescription.rejected` / `prescription.issued` / `case.closed` / `case.consult_complete` published via the outbox, so that other modules react without direct coupling.
24. As a doctor, I want the approval step structurally unable to issue the raw AI draft, so that "edit not recorded" can never mean "wrong draft issued."

## Implementation Decisions

- **Module:** build out `MOD-006` in the existing `apps/backend/modules/care/` scaffold (currently `care_identities` only) - keep its `care` Postgres schema and `care_outbox`, per ADR-0003 module isolation and ADR-0002 transactional outbox. Extend it with the case and prescription domain, following the `intake/` module layout (`facade.py`, `intake_models.py`-style DTOs, `schema/models.py`, `domain/{state_machine,events,exceptions}.py`, `adapters/routes.py`, `adapters/__init__.py`).
- **Care case:** one case per visit, born when its pre-summary is finalized. Case stages: `PreSummary -> PrescriptionPending -> Closed`. `ConsultComplete` is an audited milestone from→to on the transition, not a dwell state. `Close` is the doctor's deliberate terminal action for a visit with no prescription (recorded with close reason); a rejected draft never auto-closes.
- **Finalized pre-summary:** the handshake gate consumes the Phase-7 three-state (`draft`/`reviewed`/`final`) finally-produced summary. The `get_finalized_pre_summary` concept currently exists only in docs - implement a real getter on the intake facade (or the equivalent MOD-005 facade call) that only ever returns a `final` summary; `mark_consult_complete` is blocked otherwise.
- **AI draft:** `IntakeFacade.request_rx_draft` is already a declared stub (raises `NotImplementedError`) - Phase 8 implements it. The draft is an immutable drafting-assistant artifact: store a `draft_snapshot`.
- **Prescription statuses:** `Draft -> DoctorReviewed -> ApprovedIssued -> Fulfilled`, branch `Rejected`. `Fulfilled` rolls in from Phase 10.
- **Revision-freeze approval (the core guarantee):** the doctor's editing surface updates a working revision (the current `Draft`/`DoctorReviewed` row and its `rx_items`). Approval saves/freezes exactly that revision, sets `issued_at` + `attributed_doctor`, and derives `edited_yn` by comparing the issued revision against the immutable `draft_snapshot`. If the revision save fails, approval is blocked - the raw draft is never approvable.
- **Verification declaration:** `approve_prescription` requires `verification_declaration = true`; stored on `rx_approvals` with `declared_at`. A declaration-less approval is rejected.
- **Manual authoring:** the doctor can author `rx_items` directly with no AI draft (`prescription source = manual`); approval path is identical. This keeps AI failure from stranding a visit and is the safest compliance posture (zero AI involvement).
- **Drafting cap:** a new AI draft is only allowed while the case has < 2 rejected drafts (≤ 3 attempts total). The cap limits only draft generation - manual authoring, edit+approve, and close-without-prescription remain open regardless. Mirrors the repo's max-3 re-submission pattern.
- **Issuance immutability:** once approved & issued, a prescription is frozen; there is no supersede/void path. Corrections require a fresh visit. `get_approved_prescription(rx_id)` (the Phase-10 facade source of truth) only ever serves an approved revision.
- **One-action handshake:** `mark_consult_complete(doctor, case)` gates on finalized pre-summary, moves `PreSummary -> PrescriptionPending`, records consult-complete milestone, publishes `case.consult_complete`. Patient notification is a single hook at this point; actual delivery lands in Phase 13.
- **Doctor RBAC:** MOD-006 routes use the existing gateway pattern (`require_partner` + `PartnerFacade.resolve_partner` + `partner.partner_type == doctor`) plus active-partner check, attributing `partner_id` to all approval/rejection/close records.
- **Consent-gated drafting context:** any use of the patient's record history for drafting goes through `HealthFacade.read_consented_history` (which calls `ConsentFacade.check_consent`), fail-closed per NFR-SEC-006.
- **Schema (migration `v8_0__init_care`, following the real alembic naming - the roadmap's `v7.0__init_care.sql` label is stale):** `care_cases` (patient_id, doctor_id, pre_summary_id, stage, closed_at, close_reason), `care_prescriptions` (case_id, status, source `ai_draft|manual`, attempt_no, draft_snapshot jsonb, issued_at, attributed_doctor), `care_rx_items` (prescription_id, sequence, name, dose, duration), `care_rx_approvals` (prescription_id, doctor_id, decision, edited_yn, reason on reject, verification_declaration, declared_at, approved_at), `care_doctor_inputs` (case_id, input_type voice|photo, media ref in object storage `rx_input/`, sensitive-class), `care_outbox` + `consumed_events`. No cross-schema FKs; cross-identity columns are plain BigInteger (ADR-0003).
- **Events:** publish `pre_summary.ready`-driven case attach (inbound), `case.consult_complete` (exists), `case.closed` (new), `prescription.draft_created` (new), `prescription.reviewed` (new, optional audit marker for a saved revision), `prescription.approved` / `prescription.rejected` (existing registry rows, promote to named constants in `bus/events.py` and extend `REGULATED_ACT_TYPES`), `prescription.issued` (already reserved as `EVENT_PRESCRIPTION_ISSUED`). All via `care_outbox` in the same transaction, at-least-once, subscriber-side dedupe; `MOD-011` consumes lifecycle events for the audit schema. Subscribe: `pre_summary.ready`, `pre_summary.low_confidence` (forced-review flag before handshake), `report.filed` (case context, Phase 9).
- **CFL-002 seam:** the approval gate is implemented behind an interface so a stricter regulatory rule can slot in without redesign (per roadmap §2.8 risk matrix).
- **CFL-003:** handshake stays doctor-initiated for Phase 8; patient-initiated is explicitly deferred.

## Testing Decisions

A good test asserts external behavior through the public operation contracts and the two state machines - the issued prescription matches the approved revision, the gate blocks what it must, statuses move only legally. It does not test private helpers or HTTP particulars.

- **Primary seam - `CareFacade` boundary, faked engine** (convention: `tests/unit/test_intake_facade_capture.py`, `test_partner_facade_register.py`): faked `AsyncEngine`/`AsyncConnection` with compiled-insert assertions. Covers: mark-complete gate (finalized vs not), one-action handshake + milestone, close-without-prescription terminal, drafting cap enforcement (3rd draft blocked, manual still open), approval requiring verification declaration, revision-freeze (issued items == approved revision), `edited_yn` on edit vs no-edit, reject with required reason, outbox event writes in the same transaction, consent-gated history read through `check_consent`, doctor attribution.
- **Hard-gate prior art:** `tests/unit/test_intake_low_confidence.py` and `tests/unit/test_consent_check_gate.py` are the template for the REQ-023 hard test: zero prescriptions issued without approval + verification declaration; a declaration-less or stale-revision approval is rejected.
- **Secondary seam - pure machines** (convention: `test_intake_state_machine.py`, `test_presummary_state_machine.py`): full status×action matrix + illegal-transition raises for both `care/domain/` case and rx machines (cap, freeze-on-approve, reject branch, close terminal), no DB.
- **Tertiary seam - route boundary** (convention: `test_patient_intake_routes.py`): `create_app` + stub `CareFacade` on `app.state` + test client; only the doctor-RBAC skin - `require_partner`, doctor type check, 401/403 envelopes.
- **Repo gates kept green:** `test_module_layout.py`, `check_event_names.py`, `check_module_boundaries.py`, `npm run migration-check`, `npm run scan`, `npm run lint`, `npm run typecheck`.

## Out of Scope

- Patient-initiated handshake (open `CFL-003`, deferred).
- Supersede / void / amend of an issued prescription (frozen by design).
- Pharmacy routing and fulfillment (`MOD-008`, Phase 10) - only `get_approved_prescription` is built here; `Fulfilled` status rolls in later.
- Dosage-schedule / notification consumers (Phase 12/13) - events are published, not consumed.
- The doctor review/approve UI itself - separate prototype track; backend contracts only.
- Regulatory sign-off beyond the baseline posture (open `RISK-EVAL-003` compliance stakeholder remains; the gate seam absorbs a stricter rule later).

## Further Notes

- Cross-reference and event-registry updates ride alongside the code: `internal-modules.md` §3.6 (MOD-006 spec), §4.1 sync matrix (add `get_finalized_pre_summary` / `request_rx_draft` rows), §4.2 event registry (register `case.closed`, `prescription.draft_created`, `prescription.reviewed`, `prescription.issued`; promote approved/rejected to constants), roadmap §2.8 status, PRD §4.4/§7.1 annotate CFL-002/CFL-003 resolved, and two ADRs: `0014-issued-prescription-approval-contract.md` and `0015-ai-assisted-drafting-posture.md`.
- Phase 8 is the first consumer of the Phase-7 finalized-summary and RX-draft seams; confirm `get_finalized_pre_summary` and `request_rx_draft` behavior before wiring the handshake gate.

---

## Child Tickets (PHASE-8 implementation)

| #   | Ticket                                            | Issue | Status |
| --- | ------------------------------------------------- | ----- | ------ |
| T00 | Glossary & CONTEXT.md - MOD-006 Vocabulary (#425) | #425  | open   |
| T01 | Care Schema Migration & DTO Models                | #417  | open   |
| T02 | Case Domain - State Machine & Events              | #418  | open   |
| T03 | Prescription Domain - State Machine & Cap         | #419  | open   |
| T04 | CareFacade - Consultation Workflow                | #420  | open   |
| T05 | CareFacade - Prescription Workflow                | #421  | open   |
| T06 | Doctor Routes & RBAC                              | #422  | open   |
| T07 | Unit Tests - REQ-023 Gate & Lifecycle             | #423  | open   |
| T08 | Cross-Module Wiring & Documentation               | #424  | open   |

**Frontier:** T00 (#425) and T01 (#417) - can start immediately.
**Critical path:** T00|T01 -> T02|T03 -> T04|T05 -> T06 -> T08 (T07 joins after facade halves; T00 gates T02-T05 naming).

**Re-cut notes (2026-09-14):** T00 added (glossary naming authority); `get_finalized_pre_summary` moved into T04 and `request_rx_draft` into T05 (both were in T08, which left T04/T05 unable to complete end-to-end); T02 event-constant scope corrected; T08 now carries PRD/internal-modules/roadmap doc-delta work.
