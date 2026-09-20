# Brief - T8a PHASE-8 review-close: FEAT/issue traceability on the new care tests (docstrings)

**Ticket:** #435 · **Parent:** #426 · **Refreshed:** 2026-09-15
**Reading surface:** ~3.0K tokens (budget 10K) - within budget

## Scope

Phase-8 review-close T8a. All care unit tests added or touched by this review-close carry FEAT-008/FEAT-009 and the spec reference (#426) in their docstrings, so test origin is traceable to the product slate per the coding standard. Docstrings only - no behavioural test changes.

Acceptance criteria (verbatim from ticket):

- [ ] Every new/edited care test function or class docstring references FEAT-008 and/or FEAT-009 and #426
- [ ] No behavioural assertions are changed - docstring-only edits
- [ ] `npm run test:unit:backend`, `npm run lint` green

**Blocked by:** All of #427 (T1), #428 (T2), #429 (T3), #430 (T4), #431 (T5), #432 (T6a), #433 (T7), #434 (T6b) - the tests must exist to be tagged.

## Read-list (in order)

1. `docs/standards/coding-standards.md` §6 Tests - the `FEAT-xxx` traceability rule for test docstrings. (~0.3K)
2. The care test files touched by the review-close tickets - `test_care_facade_consult.py`, `test_care_facade_rx.py`, `test_care_routes.py`, `test_care_outbox_events.py`, `test_care_events.py`, `test_care_lifecycle_integration.py`, `test_care_req023_gate.py`, `test_care_consent_gate.py`, plus any new ownership/idempotency/envelope/inbound-consumer test files the earlier tickets added. Skim docstrings (module + function/class) only. (~2.2K)
3. `docs/prd/project-prd.md` FEAT-008 / FEAT-009 headers (as the canonical ids to cite). (~0.5K)

## Do NOT read

- Any other docs, the state machines, the facade/machine bodies, intake/partner modules, the frontend, `docs/archive/`.
- Test bodies beyond the docstring lines (no behavioural reading needed - and no behavioural edits allowed).

## Baseline verify (must pass before the first edit)

Confirmed green on this tree (HEAD `a472db1`, 2026-09-15): `npm run test:unit:backend` (2076 passed), `npm run lint` (all hooks passed). (This ticket's baseline list excludes typecheck/migration-check per its ticket.)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend`
- `npm run lint`

## Handoff notes

- Existing care tests already follow the convention `"""PHASE-8 T0X: <title> (ticket #4XX, FEAT-008/FEAT-009)."""` (see `tests/unit/test_care_events.py` module docstring) - extend that pattern to every new/edited test from the review-close set, citing #426 and FEAT-008/FEAT-009.
- Docstring-only is a hard boundary: run the suite before and after, and the only permitted diff is in `"""..."""` blocks. Any behavioural change means the earlier ticket's test was wrong - report it, don't slip a fix in.
- Which tickets' test files qualify is the union of test files touched by #427-434; grep the git diff history (or the merged branch) to enumerate exactly which test files were edited by the review-close before tagging.
