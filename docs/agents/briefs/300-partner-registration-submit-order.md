# Brief - 300 Fix partner registration submit order (Phase 5 auth fixes)

**Ticket:** #300 · **Parent:** #299 · **Refreshed:** 2026-09-04
**Reading surface:** ~2.5K tokens novel (budget 10K) - within budget

## Scope

A partner who completes the 4-step registration wizard and uploads credential documents can finish and land on their pending-status screen - the credentials upload no longer fails with HTTP 401.

Today the wizard persists the session only _after_ submitting credentials, so the credentialed upload hits the backend with no bearer token and gets 401, blocking the whole partner onboarding loop. This ticket reorders the wizard's submit so the partner session is issued and persisted first, making the JWT available when credentials are submitted.

- [ ] Submitting the wizard issues and saves the partner session _before_ it submits credential documents, so the credentials call carries a partner-scoped JWT and no longer 401s.
- [ ] The existing submit-order test passes and also asserts credential submission happens after session issue+save.
- [ ] A partner who uploaded files lands on the pending-status screen after submit (no visible 401/error).
- [ ] Full frontend unit suite passes.

## Read-list (in order)

1. **Provider registration wizard submit handler** (`handleSubmitPartner`) - the function to reorder. Current sequence: `registerPartner` -> build credential map -> `submitCredentials` -> `issuePartnerSession` -> `saveSession` -> post-login redirect. Fixed sequence: `registerPartner` -> `issuePartnerSession` -> `saveSession` -> `submitCredentials` -> redirect. Move the `credentialMap.size > 0` block to after `saveSession`. (~0.6K tokens)
2. **Wizard submit-order unit test** - the test asserting submit order on successful submit (currently asserts `registerPartner` then `issuePartnerSession` then `saveSession`, plus `submitCredentials` called once). Extend it to assert `submitCredentials` runs after `issuePartnerSession`/`saveSession`. (~0.8K tokens)
3. **Partner API client** (`submitCredentials`, `registerPartner` signatures) - confirm the request shapes you must keep stable; only call order changes, no signature change. (~0.5K tokens)
4. **Session API client + persistence** (`issuePartnerSession`, `saveSession` behavior) - confirm what the moved calls do (mint JWT, write localStorage + presence cookie). (~0.4K tokens)

## Do NOT read

- Operator/patient auth flows, backend IAM modules, `staffOperatorErrorCopy`, the proxy, dictionaries, archives.
- The wizard's dead `notice` state and header comments calling submission a placeholder - those lie; the submit performs a real registration (see handoff).

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - 58 files / 617 tests pass. Note: the process exits 1 on a _pre-existing_ teardown-timing error in `channels.test.tsx` ("window is not defined" after environment teardown, an uncleared timer). That file is unrelated to this ticket; ignore its teardown error, your suite must remain green otherwise.

## Done-verify (acceptance criteria -> commands)

- `npm run test -w @caresetu/frontend -- src/components/auth/staff/ProviderRegisterWizard.test.tsx` - submit-order tests pass.
- `npm run test:unit:frontend` - no new failures (617 pass, channels teardown error still the only non-test failure).

## Handoff notes

- The wizard also carries an unreachable `notice` render block and header comments positioned as PHASE-2.6 placeholder language. Out of scope here - do not touch them in this ticket.
- Backend already mints a partner-scoped JWT on `POST /v1/auth/partner/session` and requires a valid partner JWT on `POST /v1/partner/credentials` (RBAC). No backend change needed for this ticket.
- ADR-0005 (dual JWT storage) and ADR-0007 (split-origin) govern how the JWT is transported to the backend; the `request()` wrapper reads the JWT from localStorage via `authedFetch`. The reorder makes that JWT available at credentials time.
