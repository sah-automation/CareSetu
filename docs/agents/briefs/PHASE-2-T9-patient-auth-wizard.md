# Brief - 60 T9 - Patient auth wizard (PWA, folded from Variant B)

**Ticket:** #60 · **Parent:** #51 · **Refreshed:** 2026-08-13
**Reading surface:** ~19K tokens (budget default 50K) - within budget

## Scope

The real patient auth flow on the PWA: the chosen Variant B stepped wizard (Phone -> Verify -> Done) is folded into the patient routes and wired to the live register/verify/resend endpoints. It renders the countdown ring, resend cooldown, attempts-left, expired/used states, latest-wins notice, duplicate-registration login notice, and the brute-force lockout state, with the English/Hindi toggle. A successful verify stores the session so the patient lands on a protected page.

Acceptance criteria (verbatim):

- Phone step calls the register endpoint; invalid numbers show the validation error
- Verify step calls the verify endpoint; wrong/expired/used codes render the matching state (attempts-left, request-new-code)
- Resend respects the cooldown and latest-wins notice; lockout state renders and blocks input
- Duplicate-number flow shows the "already registered - verifying logs you in" notice
- Success stores the session and lands on the authenticated patient view; hi/en toggle works throughout
- Frontend unit tests cover the states; fold replaces the prototype route

## Read-list (in order)

1. Ticket #60 + parent spec #51 + plan `docs/plans/phase2-iam-auth-plan.md` §2/§3 - the OTP challenge contract (single-use, 5-attempt budget, latest-wins resend, 60 s cooldown, 10-failure/15-min lockout, +91 E.164) and the scope-boundary API surface (~6K, already digested).
2. Prototype source on branch `backup/t8-local-history` under `apps/frontend/src/components/prototype/otp/` (`otpState.ts` = behavioural state machine + all UI strings EN/HI; `variantB.tsx` = stepped-wizard layout contract; `shared.tsx` = the UI atoms; `OtpPrototype.tsx` = composition; the two `.module.css` = styling vocabulary) - the contract to fold. NOT on `main`; read via `git show backup/t8-local-history:<path>`. (~5K, already digested.)
3. `apps/frontend/src/app/channels.test.tsx` - the vitest + testing-library conventions (routes render via `render(<Page />)`) (~0.3K).
4. Backend API surface, HTTP only: `apps/backend/modules/iam/adapters/routes.py` (register/verify/resend shapes + error envelope), `apps/backend/modules/iam/facade.py` result models `RegisterPatientResult`/`VerifyOtpResult`/`ResendOtpResult`/`IssueSessionResult`, `apps/backend/app/main.py` (route surface + `/v1/me` + middleware) (~4K, already digested).
5. `docs/standards/coding-standards.md` §1/§3/§6 and `docs/standards/api-standards.md` §1/§2 - frontend framework lock, typing, error envelope conventions for the new route (~1.5K, already digested).
6. CONTEXT.md glossary (already read).

## Session endpoint (settled decision)

The backend exposes `issue_session(phone)` only through the facade; there is no HTTP session route, and `tests/unit/test_app_shell.py` asserts the exact route surface. Per the brief's parent decision (approved by the human), T9 adds a thin `POST /v1/auth/session` adapter (body `{phone}`, `response_model=IssueSessionResult`, same error-envelope handling as the other routes), updates `test_app_shell.py`'s route-set assertion, and adds a route test following `tests/unit/test_iam_register_route.py`'s `StubFacade` pattern. The PWA calls it only after a `verified` outcome.

## Do NOT read

- Backend internals beyond the API surface (domain internals, dispatcher, outbox, alembic migrations beyond the route shapes).
- `docs/archive/`, `phase0/`, other channels' internals, `apps/frontend/.next/`.
- The full 300-line CSS modules for line-by-line review - copy them across as styling vocabulary, do not re-derive.

## Baseline verify (must pass before the first edit)

- `npm run test:unit:frontend` - green (4 tests).
- `npm run typecheck:frontend` - green AFTER deleting the stale `apps/frontend/.next` dir (it referenced the unmerged prototype route; `.next` is gitignored). Note this cleanup in the final commit message context if relevant.

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:frontend` - new wizard state tests pass alongside the channel tests.
- `npm run test:unit:backend` - session-route test + updated `test_app_shell.py` pass.
- `npm run typecheck:frontend` and `npm run typecheck:backend` - clean.
- `npm run lint` - pre-commit (ruff + prettier + whitespace) clean.

## Handoff notes

- The prototype files live on `backup/t8-local-history`, not `main`; copy them (or their content) into the real route tree under `apps/frontend/src/`.
- `VerifyOtpResult.outcome` is `verified | wrong_code | expired | spent | locked`; the prototype's `expiredOrUsed` string maps to the `expired`/`spent` outcomes; `lockout_remaining_seconds` drives the lockout state.
- `ResendOtpResult.outcome` is `sent | cooldown | locked | suspended | no_identity`; `cooldown`/`locked` keep the resend disabled with the matching countdown, `sent` shows the latest-wins notice.
- `RegisterPatientResult.is_existing`/`flow` drive the duplicate-registration "already registered - verifying logs you in" notice.
- Invalid phone → HTTP 422 with envelope `PHONE_INVALID` (from `InvalidPhoneError`); malformed body → 422 `VALIDATION_ERROR`. The PWA must surface these as the `badPhone` string.
- `POST /v1/auth/session` returns `IssueSessionResult` (`jwt`, `jti`, `scope`, `identity_id`, `expires_in_seconds`, `refresh_token`); the PWA stores `jwt` + `refresh_token` and lands on the protected patient view.
- Reuse the prototype's EN/HI string tables and `normalizePhone` exactly - they are the behavioural contract.
