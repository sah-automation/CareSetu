# Brief - 901 Latency: add a reproducible measurement harness (feedback loop) for backend request latency

**Ticket:** #901 · **Parent:** latency epic (#901..#904 series; #901 is the prerequisite feedback loop) · **Refreshed:** 2026-11-10
**Reading surface:** ~8K tokens (budget 40K) - within budget

## Scope

Add a dependency-light backend latency measurement harness so "extremely high latency" can be quantified, attributed (server vs network), and guarded against regression. No business logic, data access, API contract, frontend, or infra changes.

Deliverables:

1. **Probe script** `scripts/measure_backend_latency.py` (stdlib-only style, matching `scripts/live_smoke.py` conventions): args `--backend-url`, `--iterations`, `--p95-threshold-ms`, `--endpoint` (repeatable), `--token` (or `LATENCY_PROBE_TOKEN` env); defaults cover `/health` plus a small set of representative authenticated patient read endpoints. Obtains a bearer token via the demo login flow (register → `/v1/auth/dev/otp` read-back → verify → `POST /v1/auth/session`) when no token is supplied. Prints a per-endpoint table (p50, p95, min, max, pass/fail) and exits non-zero if any endpoint breaches the threshold.
2. **Opt-in server timing header** on the backend (a small ASGI header middleware beside the existing gateway middlewares), gated by an env flag that defaults off in production and on in development; carries server processing milliseconds. Tagged with a unique grep-able prefix (e.g. `caresetu_tstmp`) so cleanup is a single grep.
3. **Docs**: how to run the probe and interpret output (a section the latency tickets #902/#903/#904 cite as their verification command).
4. **Unit tests** for percentile computation + threshold verdict (pure functions, fixed arrays, no network).
5. **Integration test** running the probe's logic against the in-process app for `/health` and one authenticated read endpoint; asserts zero exit code and p95 under a generous bound.

## Read-list (in order)

1. `scripts/live_smoke.py` (module docstring + `main()`/argparse region) - the script style to mirror: stdlib-only, `def main(argv) -> int`, `--backend-url`, `sys.exit(1)` on failure, ticket-coords docstring (~600 tokens)
2. `apps/backend/app/config.py` - `Settings` frozen dataclass + `_env_bool` + `from_settings` wiring + `mock_otp_readback_enabled` property (the exact recipe for the new flag: `DEFAULT_*` constant, dataclass field, `_env_bool` entry, prod-off/dev-on rule, `.env.example` line) (~800 tokens)
3. `apps/backend/app/main.py` - `create_app` (L300), the middleware stack region (L748-829: later `add_middleware` = outermost; `SecurityHeadersMiddleware`/`HttpCounterMiddleware` are the header-middleware templates), and the `/v1/auth/dev/otp` route + `MockOtpResponse` (~1200 tokens)
4. Demo login flow: `modules/iam/adapters/routes.py` (`/v1/auth/register`, `/v1/auth/verify`, `/v1/auth/session` payload shapes, all `extra="forbid"`) + `SessionResult` (`session_facade.py`: `jwt` field is the bearer) (~600 tokens)
5. `tests/integration/test_partner_login_full_loop.py` (the `_app_client` + `_otp_code` + `_bearer` helpers: `Settings(database_url=..., app_environment="test")` → `TestClient` → `GET /v1/auth/dev/otp?phone=` → `Bearer {jwt}`) - the in-process-app test pattern to reuse (~500 tokens)
6. `modules/observability/domain/rollup.py` `percentile`/`weighted_percentile` - the existing interpolation convention; the probe's standalone percentile math should stay consistent with it (nearest-rank vs linear) (~300 tokens)
7. `scripts/loadtest/run.cjs` + `package.json` npm-script wiring (`node scripts/py.cjs scripts/<name>.py`) - how to add an npm wrapper + the related-but-distinct k6 harness to cite, not supersede (~300 tokens)

## Do NOT read

- `docs/archive/`, the observability rollup internals beyond `percentile`, the OTel exporter config, any frontend code, k6 scenario internals, `docs/adr/*` (no ADR gates this; no auth/cookie/CORS changes - the probe is a plain HTTP client)

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - 4392 passed, 2 skipped (2026-11-10, green)
- `npm run typecheck` - run before first edit to confirm the tree is clean
- `npm run test:integration` (2026-11-10, clean tree): 531 passed, 1 pre-existing failure - `tests/integration/test_consent_check_gate.py::test_p95_latency_under_50ms` (best-effort 50 ms perf assertion; p95 ~171-241 ms on this machine, fails standalone too; unrelated to this ticket and out of its scope - it is exactly the unquantified latency #901 instruments)

## Done-verify (acceptance criteria → commands)

- `npm run test:unit:backend` - new percentile/verdict unit tests pass
- `npm run test:integration` - new in-process probe integration test passes (needs local PostgreSQL; skips if unreachable)
- `npm run typecheck` - mypy `--strict` clean for new backend code
- `npm run lint` - clean
- Manual: `npm run <probe-wrapper> -- --backend-url http://localhost:8000 --iterations 5` against a dev server prints the table and exits 0

## Handoff notes

- **Rate limiter:** `/v1/auth/*` is rate-limited per client IP; the probe must hammer only the measured endpoints (bearer-authenticated) and never the OTP surface in its measurement loop. Fetch the token once up front. If a probe run hits local rate limiting, the `scripts/loadtest/run.cjs` precedent (`GATEWAY_RATE_LIMIT_ENABLED=false`) is the local-run posture.
- **Token fallback:** `/v1/auth/dev/otp` 404s unless `SMS_PROVIDER=mock` AND (`APP_ENVIRONMENT` in {dev,test} OR `DEMO_MODE=true`). The probe's `--token`/env path is the production fallback; the demo read-back path is dev/demo-only.
- **Header scope:** the Server-Timing-style header is developer-facing debug only - not a telemetry source (OTel `METRICS_ENABLED` already histograms server latency). Instrumentation tagged `caresetu_tstmp` (single-grep removal per user story 7).
- **Sibling tickets** #902/#903/#904 depend on this probe's exit code as their before/after gate - keep the CLI surface stable once shipped.
- Backend root is `apps/backend/` (not repo root); new backend unit tests go in `tests/unit/`, integration in `tests/integration/`.
