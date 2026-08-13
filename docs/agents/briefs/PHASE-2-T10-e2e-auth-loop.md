# Brief - 61 T10 - Playwright E2E auth loop

**Ticket:** #61 · **Parent:** #51 · **Refreshed:** 2026-08-13
**Reading surface:** ~10K tokens (budget default ~10K) - within budget

## Scope

The full Phase 2 release loop is proven end to end in the browser: register -> OTP (mocked SMS) -> verify -> authenticated session -> access a protected route. The Playwright E2E suite drives the real PWA against the running backend with the mock SMS adapter, including the duplicate re-registration case resolving to the existing identity, and covers the release readiness criteria from roadmap §2.2.

Acceptance criteria (verbatim):

- E2E: register a new number, read the mock OTP, verify, land on the protected route with a valid session
- E2E: re-registering the same number resolves to the existing identity and logs in (no duplicate)
- E2E: an unauthenticated attempt at the protected route is denied
- E2E suite runs green in CI against the mocked SMS adapter (no real provider)

## Seams the ticket requires (decided here - do not re-derive)

These are gaps a fresh implementer would rediscover; the implementation just conforms to them:

1. **Backend in Playwright webServer.** `playwright.config.ts` boots only the frontend today. Add a second `webServer` entry that (a) runs `alembic upgrade head` against Postgres, then (b) boots `uvicorn app.main:app --port 8000` with cwd `apps/backend`. The boot command must work both locally (backend-env venv, `node scripts/py.cjs -m ...`) and in CI (`uv run --project apps/backend ...`) - a small wrapper script under `scripts/` is the clean seam. Backend env for the e2e: `GATEWAY_JWT_VERIFY_ENABLED=true` + `GATEWAY_JWT_SIGNING_KEY=<dev key>` (so the protected-route denial is real), `SMS_PROVIDER=mock`, `APP_ENVIRONMENT=test`; leave `GATEWAY_RATE_LIMIT_ENABLED` off so the suite never trips the 10/60 s auth cap.
2. **Frontend webServer url probe.** The current probe `url: "http://localhost:3000"` 404s (there is no root page; `/patient` is the entry) and Playwright's probe rejects non-404, so the suite times out at 120 s. Point it at `http://localhost:3000/patient` (renders the wizard with 200).
3. **Mock-OTP read surface.** `MockSmsAdapter.last_sent_code(phone_e164)` is the only plaintext OTP source and it lives in the backend process - no HTTP endpoint exposes it. Add a dev-only route that answers the most recently sent code for a phone, gated to `sms_provider == "mock"` AND `app_environment in {dev, test}` (mirrors `_DEV_TEST_ENVIRONMENTS` in `app/config.py`). Suggested shape: `GET /v1/auth/dev/otp?phone=<e164>` -> `{"code": "123456"}` / `{"code": null}`. It reads the running instance's mock adapter (the facade's `_sms`). Add a route test, and update `tests/unit/test_app_shell.py`'s exact route-set assertion (it currently asserts the full OpenAPI path set).
4. **CORS.** The browser on :3000 calls the API cross-origin (:8000) directly - no Next proxy exists, and the backend has no CORS middleware. Add `CORSMiddleware` allowing `http://localhost:3000` in the app shell `create_app`. api-standards has no CORS rule today; this is the new seam.
5. **CI e2e job.** `ci.yml` has a placeholder comment where the Phase 2 e2e job lands. Add it modeled on the `integration` job: postgres:16-alpine service (caresetu user/db) + node 24 + `npm ci` + `uv sync --project apps/backend --group dev` + `npx playwright install --with-deps chromium`, then `npm run test:e2e` with `DATABASE_URL` and the backend env above. The webServer config starts both servers (and runs the migration), not the job.

## Read-list (in order)

1. Ticket #61 + parent spec #51 (Implementation Decisions §3-§5, Testing Seams, Further Notes) + ticket #60 - the release loop, OTP contract, and wizard behavior the suite must prove (~2.5K, mostly digested above).
2. `playwright.config.ts` + `tests/e2e/README.md` - current webServer wiring and the planned backend hookup (~1K).
3. Backend boot surface: `apps/backend/app/config.py` `Settings` keys (gateway flags, sms_provider, app_environment, `_DEV_TEST_ENVIRONMENTS`), `scripts/py.cjs` (venv invocation), `apps/backend/app/main.py` `create_app` (middleware stack, `/v1/me`, `app.state.iam_facade`) (~2K).
4. Mock adapter read surface: `apps/backend/modules/iam/adapters/sms.py` `MockSmsAdapter` (`last_sent_code`, `sent_count`) - the OTP source the dev route wraps (~0.8K).
5. `apps/backend/modules/iam/adapters/routes.py` route-adapter pattern (typed request -> facade -> typed result, error envelope) + `tests/unit/test_app_shell.py` route-set assertion (~1.2K).
6. Frontend wizard slices: `apps/frontend/src/components/auth/otp/otpState.ts` STRINGS.en + `PatientAuthWizard.tsx` (DOM markers the suite asserts) + `apps/frontend/src/lib/auth/session.ts` (localStorage keys) - grep the referenced slices only (~1.5K).
7. `.github/workflows/ci.yml` `integration` job (Postgres service + uv + pytest env) as the e2e-job template (~1K).

## Do NOT read

- Backend domain internals (otp.py, jwt.py, refresh.py, facade internals, outbox/dispatcher), alembic migrations, `docs/archive/`, `phase0/`, other channels' internals, the prototype folder, `apps/frontend/.next/`, the 300-line CSS modules.

## Baseline verify (must pass before the first edit)

- `npm run test:e2e` - currently FAILS (starting truth): no e2e tests exist AND the frontend webServer probe on `/` 404s, timing out at 120 s. The frontend dev server itself boots in ~1 s; the probe URL is the problem.

## Done-verify (acceptance criteria -> commands)

- `npm run test:e2e` - the new auth-loop suites pass (register+verify+session+protected route; duplicate re-registration resolves to the same identity; unauthenticated denial; signed-in session survives reload).
- `npm run test:unit:backend` - dev-OTP route test + updated `test_app_shell.py` route-set pass.
- `npm run typecheck` and `npm run lint` - clean (pre-commit lints the new CI YAML).

## Handoff notes

- Wizard DOM/string markers the e2e drives (from T9, verified on main): phone step at `/patient` with placeholder "10-digit mobile number" and submit "Get verification code"; duplicate notice "This number is already registered - verifying logs you in."; OTP input `aria-label="Verification code"`; resend "Resend code"; verify submit "Verify & continue"; done step "Identity verified" -> "Go to CareSetu home"; authenticated home "You're signed in" + "Signed in as +91...". Sign-out clears the session and returns to the phone step.
- Session storage keys: `caresetu.access_jwt`, `caresetu.refresh_token`, `caresetu.session`. Auth-gating is component-level: unauthenticated `/patient` renders the phone form; a signed-in reload renders `AuthenticatedHome` (no URL redirect, no `/v1/me` call from the PWA).
- API base is `http://localhost:8000` (frontend default, no proxy). Endpoints: `POST /v1/auth/register|verify|resend|session`; protected proof route `GET /v1/me` (200 with `subject_id`/`roles` for a valid access JWT, 401 otherwise) - assert denial via Playwright's `request` fixture against `/v1/me`.
- `VerifyOtpResult.outcome` is `verified | wrong_code | expired | spent | locked`; `RegisterPatientResult.is_existing`/`flow` drive the duplicate notice. `POST /v1/auth/session` returns `IssueSessionResult` (jwt, jti, scope, identity_id, expires_in_seconds, refresh_token).
- Local Postgres is reachable (caresetu:caresetu@localhost:5432/caresetu) but the `iam` schema has NOT been migrated - the backend webServer command running `alembic upgrade head` is what makes the suite self-bootstrapping.
- Duplicate re-registration e2e: after a successful register+verify, sign out, enter the same number again -> register answers `is_existing=true` -> the notice renders -> verify logs back in against the SAME identity.
- Exposing the mock OTP over a dev-only route is acceptable because it is gated to mock provider + dev/test environment and OTPs are ephemeral single-use values; it never runs in production.
