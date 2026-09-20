# Brief - 470 F014-T10 Integration: full partner login loop on live Postgres

**Ticket:** #470 · **Parent:** #460 · **Refreshed:** 2026-09-17
**Reading surface:** ~7K tokens (budget 10K) - within budget

## Scope

The whole partner leg is proven as one vertical flow on live Postgres, asserted at the HTTP seam: a doctor registers, confirms their phone by OTP, obtains a partner session, submits credentials, reads their status, is activated by an operator decision, and reaches the partner home - all through the public routes. The activation chain still grants the partner role only through the operator decision (never at login). A single phone holding both roles behaves as decided: partner login never creates or grants the patient role, and the patient act stays separate.

Acceptance criteria (verbatim from ticket):

- [ ] Integration test drives the full loop end-to-end at the HTTP boundary: register → confirm phone → session → submit credentials → status → operator activation → reach partner home.
- [ ] Test proves the partner role grant exists only after the operator activation event, never at login/verify/session time.
- [ ] Test proves partner verify for a shared phone produces no patient role grant and no `patient.verified` event, and that a patient session for that phone requires the separate patient act.
- [ ] Existing partner credential-account and partner role-chain integration tests still pass (they may be extended, not weakened).

**Blocked by:** #464 (tighten session mint), #465 (partner renewal), #466 (state-based gating) - the backend behaviour under test must exist first.

## Read-list (in order)

1. The integration harness `tests/integration/conftest.py` (`db_engine`, `throwaway_schema`, `reachable_db`, `seed_daltonganj_service_area`; module-scoped alembic `command.upgrade(config, "head")` then `downgrade`, per-test TRUNCATE of module tables, real facades + `MockSmsAdapter`, async `pytest_asyncio` tests) - the setup pattern the new loop test uses. (~1.5K)
2. Prior-art loop suites: `tests/integration/test_iam_partner_role_chain.py`, `test_iam_partner_credential_account.py`, `test_iam_session.py`, `test_iam_verification.py` (+ the operator decision + partner registration/credential suites) - the HTTP-seam/real-facade assertion style to extend, and the rows that must keep passing. (~4K)
3. The route + outcome shapes from backend tickets #462-465 (auth partner login/verify/session, refresh) and #466 (self-service gates) - read the briefs 462-466 in this folder rather than re-reading source; the operator decision route shape for the activation step. (~1K)

## Do NOT read

- Frontend code, `docs/archive/`, unit-test internals, operator console internals beyond the decision route the loop needs, partner-domain internals beyond state transitions.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` (2184 passed on 2026-09-17), `npm run lint`, `npm run typecheck`.
- `npm run test:integration` - REQUIRES live native PostgreSQL (`TEST_DATABASE_URL`/`DATABASE_URL`, default localhost:5432 caresetu). On 2026-09-17 the local service is reachable; the focused loop-shape subset (`test_iam_partner_role_chain`, `test_iam_partner_credential_account`, `test_iam_registration`, `test_iam_session`, `test_iam_verification`, `test_partner_registration`, `test_partner_credentials`) passed 58/58. The full suite runs long (~>15 min) - record whether it ran. Suite skips cleanly when Postgres is unreachable (do NOT let a skip masquerade as a pass for this ticket).

## Done-verify (acceptance criteria → commands)

- `npm run test:integration` green with the new loop test; the existing partner role-chain / credential-account suites still green.
- `npm run typecheck`, `npm run lint` green.

## Handoff notes

- Assert at the public HTTP boundary / real facades - external behavior only (outcomes, refusals, which events exist, scope grants), never private tables or internal method calls.
- Prove the role-grant timing: query the ledger/role-grant state after verify and after session mint to show NO `partner` grant exists until the operator activation event fires; only then does the loop reach the partner home.
- Shared-phone dual-role proof: a phone that later becomes a patient must (a) produce no patient role grant and no `patient.verified` envelope from any partner login/verify/session step, and (b) REQUIRE the separate patient registration/verify act to mint a patient session.
- The throwaway-schema fixture means each test runs on its own Postgres schema then drops it - use it for the loop; re-seed `seed_daltonganj_service_area` if the truncate wipes it (registration defaults a partner without a declared area to Daltonganj).
- Sequence AFTER #464-466 merge; the loop exercises the OTP machine through real `MockSmsAdapter` + the dev read-back or direct challenge - keep it at the seam, no shortcut seeds.
