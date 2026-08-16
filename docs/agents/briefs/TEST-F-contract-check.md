# Brief - 132 TEST-F - OpenAPI vs frontend client contract check

**Ticket:** #132 · **Parent:** #126 (TEST-SUITE) · **Refreshed:** 2026-08-15
**Reading surface:** ~2.5K tokens (budget 10K) - within budget

## Scope

Prevent the frontend/backend drift class of bug hit during DEPLOY-7 (field-name mismatch, 422s): `scripts/contract_check.py` validates the frontend auth client's request/response shapes (the `apps/frontend/src/lib/auth/api.ts` interfaces) against the backend's `/openapi.json`. Hard-fail on PR + merge via a new `ci.yml` job.

Acceptance criteria (verbatim):

- The checker reads the backend OpenAPI schema and verifies each frontend auth client request path, method, and request/response shape resolves
- A mismatch (missing endpoint, renamed field, wrong type) fails the check with a clear diff-style message
- A ci.yml job runs the check on PR + merge and passes on the current tree

## Read-list (in order)

1. `apps/frontend/src/lib/auth/api.ts` - the client's request/response shapes: `RegisterResult`, `VerifyResult`, `ResendResult`, `SessionResult`, `DemoOtpResult`, `ErrorEnvelope`, and the five functions (`registerPhone`, `verifyOtp`, `resendOtp`, `issueSession`, `fetchDemoOtp`) with their paths/methods (~0.8K).
2. `apps/backend/modules/iam/adapters/routes.py` - the `POST /v1/auth/register|verify|resend|session` + `GET /v1/auth/dev/otp` routes and their request/response models (`RegisterPatientRequest`, `VerifyOtpRequest`, `ResendOtpRequest`, `IssueSessionRequest`, `RegisterPatientResult`, `VerifyOtpResult`, `ResendOtpResult`, `SessionResult`, `MockOtpResponse`) (~0.8K).
3. `apps/backend/app/main.py` - the FastAPI app assembly (`app.openapi()` / `GET /openapi.json`), `/health`, `/v1/me` (`MeResponse`) and how the schema is generated (~0.5K).
4. Plan `docs/plans/test-suite-plan/production-test-suite-plan.md` §3.F - contract-check intent + hard-fail posture (~0.2K).
5. `.github/workflows/ci.yml` - where the new job slots; how the backend is booted (`uv run --directory apps/backend`, Postgres service) so `/openapi.json` can be fetched (~0.4K).

## Do NOT read

- `docs/archive/`, the frontend wizard components, unrelated module specs.

## Baseline verify (must pass before the first edit)

- `npm run lint`, `npm run typecheck`, `npm run test:unit` (all green on 2026-08-15).

## Done-verify (acceptance criteria → commands)

- The checker passes locally against the running app's `/openapi.json`, and the ci.yml job is green.

## Handoff notes

- The frontend client and backend models currently agree (verified in recon, 2026-08-15) - the checker should pass on the current tree, which is its acceptance bar.
- The checker needs the backend's `/openapi.json`. The lightest CI path is to boot the app in the job (Postgres 16-alpine service + `uv run --directory apps/backend`) and fetch the schema; a local fallback (`python -c "import app.main"` style, or against a running dev server) is fine for local runs.
- Mismatch output must be diff-style and name the field/path that drifted (e.g. `RegisterResult.outcome: "no_identity" missing in OpenAPI`), not a raw JSON dump.
- `fetchDemoOtp` returns `string | null` and tolerates 404 (`DEV_OTP_UNAVAILABLE`) - the checker should treat that route's optionality as in-band, not a mismatch.
