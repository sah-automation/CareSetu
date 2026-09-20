# Brief - T3 PHASE-8 review-close: close-without-prescription operation, route and case.closed publisher

**Ticket:** #429 · **Parent:** #426 · **Refreshed:** 2026-09-15
**Reading surface:** ~8.6K tokens (budget 10K) - within budget

## Scope

Phase-8 review-close T3. A doctor can close a visit with no prescription in one deliberate action. A new facade operation is legal only from PrescriptionPending (via the existing case-machine close action), records closed_at and a required close_reason, moves the case stage to Closed, and publishes `case.closed` through the care outbox in the same transaction as the close write. A new doctor-RBAC route exposes it with a required close reason. A rejected AI draft never closes the case - closing stays the doctor's deliberate action.

Acceptance criteria (verbatim from ticket):

- [ ] Close-without-prescription terminal from PrescriptionPending only; any other stage raises the illegal-transition error
- [ ] close_reason is required and recorded with closed_at; stage transitions to Closed
- [ ] `case.closed` is enqueued to the care outbox in the same transaction as the close write (same-transaction assertion)
- [ ] A rejected AI draft leaves the case open (stage unchanged, no close)
- [ ] Doctor-RBAC route exposed with a required close reason (missing reason is a 400/validation failure)
- [ ] `npm run test:unit:backend`, `npm run lint`, `npm run typecheck` green (new facade, route, and outbox tests)

**Blocked by:** #427 (T1) - schema head must be stable before the close writes land.

## Read-list (in order)

1. `care/domain/state_machine.py` - the case machine's `CLOSE_WITHOUT_RX` action, its stage gate, the non-empty `close_reason` requirement, and `Closed` terminality. This is the operation's legality floor. (~1.2K)
2. `care/domain/events.py`: `CaseClosedPayload` + `case_closed_envelope` builder - the envelope shape `case.closed` must be published with (producer `care`). Also note `prescription.rejected` never touches the case stage. (~0.8K)
3. `care/facade.py` `reject_prescription` block (~L784-882) - the closest existing op: load case + rx, run machine transition, publish via `write_outbox` in one `engine.begin()`. Mirror it for the new `close_case_without_rx`. (~1.2K)
4. `care/care_models.py` `CaseDetailView` - how `stage`, `closed_at`, `close_reason` are modelled/validated on the returned view (Close is terminal, so the view carries them). (~0.6K)
5. `bus/outbox_writer.py` `write_outbox` signature - the same-transaction publisher call contract. (~0.4K)
6. `care/adapters/routes.py` - the doctor-RBAC route pattern: `require_partner` + `_require_doctor` resolving the doctor id, one existing POST handler (e.g. `mark_consult_complete` or `submit_doctor_input`) as the shape for the new close route, plus the validation-failure envelope handling. (~1.4K)
7. Tests as prior art: `test_care_outbox_events.py` same-transaction `engine.begin.assert_called_once()` pattern, `test_care_facade_consult.py` transition + outbox harness, `test_care_routes.py` stub-facade route tests, and the `test_care_lifecycle_integration.py` close-without-RX walk. Targeted slices only. (~2.6K)

## Do NOT read

- Prescription machine internals beyond the reject path, intake/partner/iam internals, the frontend, `docs/archive/`.
- The AI-draft internals of `care/facade.py` (`_create_ai_draft`), the consent-gate helpers, or history assembly - unrelated to this ticket.

## Baseline verify (must pass before the first edit)

Confirmed green on this tree (HEAD `a472db1`, 2026-09-15): `npm run test:unit:backend` (2076 passed), `npm run migration-check` (single head, no cross-schema FK), `npm run lint` (all hooks passed), `npm run typecheck:backend` (no issues).

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new close facade tests, route tests (missing-reason 400), outbox same-tx test, rejected-draft-no-close test
- `npm run lint`
- `npm run typecheck`
- `npm run scan` (bandit/audit/secrets listed in the ticket's done-verify)

## Handoff notes

- **There is no close operation today.** `CLOSE_WITHOUT_RX` exists only as a case-machine action and `case.closed` only as an envelope builder in `domain/events.py`; no facade method, no route, no outbox publish. This ticket builds the operation end to end.
- The case machine's `CLOSE_WITHOUT_RX` requires a non-empty `close_reason` and is terminal to `Closed`; it is already illegal from non-PrescriptionPending stages (you must pass through a PrescriptionPending-legal state via the same machine call that `mark_consult_complete` uses, so the machine is the gate, not extra checks).
- "Rejected draft never closes" is already structurally true - `reject_prescription` transitions only the prescription machine and never writes `care_cases.stage`; your test must assert stage is unchanged, not add new logic.
- `case.closed` subscribers per `internal-modules.md` §4.2: MOD-010 (patient notification, Phase 12/13) and MOD-011 (audit) - neither is built yet; you only publish via the care outbox.
- The route is `POST /v1/care/cases/{case_id}/close` under the doctor-RBAC guard with a required body `close_reason`; validation failures must return the standard error envelope (T7 fixes envelope copy later - keep `CARE_VALIDATION_ERROR`/`ILLEGAL_CARE_TRANSITION` codes used by the existing handler registration in `care/adapters/routes.py`).
- #427 (T1) must land first (schema head stable). Check its closing comments before writing the facade insert - `closed_at`/`close_reason` columns already exist in `care_cases` (schema v8.0) and are NOT null-constrained, so the DB needs no migration for this ticket.
