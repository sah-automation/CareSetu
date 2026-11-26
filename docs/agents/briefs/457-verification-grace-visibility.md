# Brief - 457 Re-verification grace window: pending new-round credentials must not de-list an Active partner

**Ticket:** #457 · **Parent:** #455 · **Refreshed:** 2026-09-17
**Reading surface:** ~5K tokens (budget 10K) - within budget

## Scope

An `Active` partner who re-submits credentials (a new re-verification round, opened whenever an approved partner adds a credential) must stay directory-visible for the 7-day grace window. The read-side visibility predicate must derive validity from the partner's approved-round credential set so pending new-round (unverified) rows cannot de-list them. De-listing happens only on an operator decision: approve refreshes the index (activation seam from #456), reject deindexes (`close_out_credentials`, unchanged).

Acceptance criteria:

- [ ] An `Active` partner who submits a new re-verification round (extra credential) remains visible in directory search during the grace window.
- [ ] An operator rejection of that round still de-lists the partner (close-out path unchanged - or validated).
- [ ] Operator approval of that round keeps/refreshes the partner's visibility (activation seam).
- [ ] Unit test covers the re-submission-then-search sequence; no compensating event or read-modify-write is required because the read is now correct.

## Read-list (in order)

1. `provider_visible`, `has_any_credential`, `has_invalid_credential` in the credential-validity deep module - the predicates to fix and where `verified`/round scoping lives (~2K).
2. `CredentialIntakeFacade.submit_credentials` re-verification path: how a new round's `partner_credentials` rows are ingested (`verified = false`), and the `START_VERIFICATION` round increment (~2K).
3. How the "current/approved round" is recorded - `partner_profiles.round` vs `partner_credentials.round` vs `partner_verifications.status` on the verification rows; pick the authoritative one for scoping the visibility predicate (~1K).
4. `tests/unit/test_credential_validity.py` and `tests/integration/test_partner_grace_window.py` - predicate + grace-window integration test style (~1.5K).

## Do NOT read

- Operator-gate queue/detail reads, artifact store, worker-bus wiring, unrelated modules, `docs/archive/`.
- Migration internals (that is #458).

## Baseline verify

- `npm run test:unit:backend` (minus the 3 recorded OTP config failures) and `npm run typecheck` green on the partner slice; `npm run migration-check`.

## Done-verify

- New grace-visibility unit test + full `npm run test:unit:backend` + `npm run typecheck`.
- Integration grace-window scenario still green.

## Handoff notes

- The fully-unscoped `has_invalid_credential` predicate is the root cause: it scans ALL rounds for any unverified/expired/revoked row. Keep the lazy read-hide (ADR-0011) philosophy - the fix is scope (approved-round rows count), not caching.
- #456's activation transition stamps the CURRENT round's rows `verified = true` on approval - your predicate's notion of "approved round" must agree with that seam so approve keeps visibility.
- Reject path is `close_out_credentials` from `operator_decision` (deindex once per partner) - unchanged by this ticket, only validated.
