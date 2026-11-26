# Brief - T4 PHASE-8 review-close: facade-enforced doctor scope, one ownership guard, real machine handshake gate

**Ticket:** #430 · **Parent:** #426 · **Refreshed:** 2026-09-15
**Reading surface:** ~9.9K tokens (budget 10K) - within budget (facade body largely already loaded from T2/T3 context)

## Scope

Phase-8 review-close T4. Doctor scope moves to the facade boundary: every single-case read and write is ownership-checked inside the facade through one shared guard, returning the not-found envelope unless the doctor owns the case, so a route-level mistake can never expose another doctor's case or prescription. `get_approved_prescription` gains the authenticated-doctor parameter and refuses unless the doctor owns the case. A born case (doctor_id not yet assigned at case birth) is claimable by the first doctor who completes the consult-complete handshake, and is enforced by the guard from then on. The handshake passes the real finalized-pre-summary result into the state-machine transition so the machine's own gate blocks unreviewed summaries. Comments document the facade verification-declaration gate as the one replaceable CFL-002 seam, with the machine's guard as defense-in-depth.

Acceptance criteria (verbatim from ticket):

- [ ] One shared ownership guard exists and is called by every case-scoped operation; no duplicated check remains at call sites
- [ ] A foreign doctor on any case-scoped read or write, including `get_approved_prescription`, gets the not-found envelope
- [ ] An unclaimed born case (doctor_id unset) can be claimed by the doctor performing the handshake; after claim, ownership is enforced
- [ ] `mark_consult_complete` resolves the finalized pre-summary first and passes the real result into the case-machine transition (the machine's gate is the boundary)
- [ ] CFL-002 seam comments present at the facade declaration gate noting the deliberate machine defense-in-depth
- [ ] `npm run test:unit:backend`, `npm run lint`, `npm run typecheck` green, including new ownership tests

**Blocked by:** #428 (T2) - born cases carry no doctor until claim under this ticket; #429 (T3) - close-without-prescription is a case-scoped operation the guard must cover.

## Read-list (in order)

1. `care/facade.py` - the case-scoped operations the guard must cover. Read the ownership-check sites (the load-case-then-reject-if-foreign pattern in `mark_consult_complete`, `submit_doctor_input`, `create_rx_draft`, `save_rx_revision`, `approve_prescription`, `reject_prescription`, T3's new close op) and `get_approved_prescription` (~L884-928, today NO doctor param, NO ownership check). Extract ONE guard and call it everywhere; add the doctor parameter to the approved-read. Structurally skimmable - the bodies were already loaded in T2/T3. (~6.5K)
2. `care/domain/exceptions.py` - `CareNotFoundError` (the not-found envelope) vs `CareValidationError` vs illegal-transition errors; the guard raises from the correct type. (~0.4K)
3. `care/domain/state_machine.py` `MARK_CONSULT_COMPLETE` transition - the `pre_summary_finalized: bool` gate for the real-result handshake; `CaseState` snapshot dates. (~0.8K)
4. `intake/facade.py` `get_finalized_pre_summary` contract (~L614-665) - returns the view only when `review_state == final`, raises otherwise; the handshake must resolve this first and pass the real result into the transition. (~0.6K)
5. `care/adapters/routes.py` approved-prescription read (~L386-405) and `_require_doctor` (~L70-88) - the route must fetch the principal and forward doctor/scopes into the facade; routes stay thin adapters. (~0.6K)
6. Ownership test prior art: `test_care_facade_consult.py` / `test_care_facade_rx.py` faked-engine harnesses + the route tests' stub-facade pattern - where the new "foreign doctor on every op gets not-found" tests land. (~1.0K)

## Do NOT read

- Intake internals beyond the `get_finalized_pre_summary` contract, idempotency wiring, partner/iam internals, the frontend, `docs/archive/`.
- The AI-draft/consent-gate internals of the facade (`_create_ai_draft`, history assembly) - none of this ticket's edits touch them.

## Baseline verify (must pass before the first edit)

Confirmed green on this tree (HEAD `a472db1`, 2026-09-15): `npm run test:unit:backend` (2076 passed), `npm run migration-check` (single head, no cross-schema FK), `npm run lint` (all hooks passed), `npm run typecheck:backend` (no issues).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new ownership tests (foreign doctor not-found on every case-scoped op incl. approved-read), claim-on-handshake test, real-machine-gate test, CFL-002 comment presence (comment, so review-only)
- `npm run lint`
- `npm run typecheck`

## Handoff notes

- Ownership today is buried at each call site as an inline `row.doctor_id != doctor_id` pattern raising `CareNotFoundError`, and `get_approved_prescription` has **no** doctor scoping at all (routes guard it, facade does not). T4 collapses the checks into one shared guard and adds the missing parameter + check.
- Claim semantics: T2's birth write must NOT set `doctor_id` (unclaimed); `mark_consult_complete` is the claim point - the guard must allow a doctor to operate on an unclaimed case exactly for the handshake and then enforce ownership thereafter. Confirm T2's insert omits doctor_id when implementing (tie-out needed).
- The handshake currently passes a hard-coded `pre_summary_finalized=True` into the machine after an external gate check; T4 moves the resolution first (`get_finalized_pre_summary`) and passes its real result so the machine's own gate is the single boundary.
- `get_approved_prescription`'s other caller in the future is MOD-008 (fulfillment, Phase 10) per the sync matrix - the new doctor parameter is added by `internal-modules.md`'s spec and the route; there is no fulfillment caller on the tree yet, so the signature change is safe now.
- CFL-002: the facade `_check_approval_declaration` gate + machine declaration guard are deliberate two-layer defense; add comments naming the facade gate as the replaceable compliance seam (ADR-0014/0015) and labelling the machine guard defense-in-depth. T7 later fixes envelope copy; keep raising typed care exceptions.
