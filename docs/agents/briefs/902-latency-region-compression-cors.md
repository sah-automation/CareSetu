# Brief - 902 Latency: co-locate backend with database (Singapore region) and enable response compression

**Ticket:** #902 · **Parent:** #901 (measurement harness, shipped in 6e3c1b7) · **Refreshed:** 2026-11-11
**Reading surface:** ~9K tokens (budget 40K) - within budget

## Scope

Three latency levers plus operator docs. Code changes are agent-implementable; the Region move itself (Render dashboard recreation, secret entry, Vercel env update) is human-run, documented in this ticket's deployment steps.

1. **Region co-location (manifest only):** `render.yaml` gains an explicit `region: singapore` on the web service matching the database region, with a comment noting that changing a Render region requires service recreation, not an in-place update.
2. **Response compression:** the backend registers GZip middleware with a sensible minimum payload size (default 1024 bytes), toggled by settings.
3. **CORS preflight cache:** the CORS middleware sets a long `max_age` (default 24h) so browsers stop re-preflighting every call.

Unit tests for both (compression on large JSON, not on small; preflight responses carry the configured `access-control-max-age`).

4. **Docs:** the deployment plan gains a region co-location section: region rationale, secret re-seed checklist for recreating the service, frontend base-URL update, keep-warm workflow URL update (`LIVE_BACKEND_URL` repository variable), keep-alive cron behavior and cold-start expectations, and old-service retirement steps.

**Out of scope:** database region change or migration; N+1/transaction work (#903 separate); frontend data-fetching changes (#904 separate).

## Read-list (in order)

1. `apps/backend/app/main.py` middleware region (L740-838) - the add-stack: last `add_middleware` wins (outermost). GZip goes in OUTER to the gateway stack but INNER of `ServerTimingMiddleware` so the #901 probe's full-stack window stays outermost (its commit comment pins ServerTiming as outermost user middleware). `CORSMiddleware` is registered at L780 with no `max_age` today (Starlette default 600 s)
2. `apps/backend/app/config.py` - the Settings recipe: fields near `cors_allowed_origins` (L460), `from_settings` wiring near L1578, `_env_bool`/`_env_int` helpers, `DEFAULT_*` constants, `.env.example` blocks near L190-201 as the comment style
3. `tests/unit/test_app_shell.py` L381-424 - the prior art: `_cors_allow_origins` middleware-introspection helper + `Settings(cors_allowed_origins=...)` tests + the `TestClient(create_app())` preflight/header asserts; new tests mirror this file
4. `render.yaml` (whole file, short) - where `plan: free` / service keys live; add `region` beside them
5. `docs/plans/deployment-plan/portfolio-deployment-plan.md` §1-2 - where the docs section goes and the deploy vocabulary (deploy hook, `autoDeploy: false`, dashboard-managed secrets) already used
6. `docs/agents/latency-probe.md` - the before/after gate: `npm run check:latency` output and exit codes cited by this ticket
7. `.github/workflows/keep-warm.yml` - the cron the docs must retarget (uses the `LIVE_BACKEND_URL` repository variable)

## Do NOT read

- `docs/archive/`, `docs/adr/*` (ADR-0007's session invariants are unaffected: no cookie/session/origin rule changes; CORS max-age is a browser hint, not an origin rule), any module interiors beyond the middleware stack, observability internals, frontend code, k6/nightly internals
- The OTel exporter / cardinality config - unrelated latency axis

## Baseline verify (must pass before the first edit)

- `npm run test:unit:backend` - green on the shipped tree (post-#901: 4392+ tests)
- `npm run typecheck` - clean
- `npm run lint` - clean
- (Network-dependent, human-run for numbers; not a gate for the code change): `npm run check:latency -- --backend-url https://<render>.onrender.com --iterations 20` before/after the Region move records the delta the ticket promises (~250-350 ms RTT removed)

## Done-verify (acceptance criteria -> commands)

- `npm run test:unit:backend` - new compression + preflight max-age tests pass
- `npm run typecheck` - mypy `--strict` clean
- `npm run lint` - clean (pre-commit: prettier covers the markdown/manifest)
- `npm run check:latency` CLI surface untouched (sibling tickets #903/#904 depend on it)

## Handoff notes

- **Middleware order rule:** later `add_middleware` = outermost. Register GZip right before the ServerTiming block so the compression wraps the gateway but ServerTiming still wraps compression; the Server-Timing header survives compression (headers untouched).
- **Starlette facts:** `CORSMiddleware(allow_origins=..., max_age=...)` echoes `access-control-max-age` on the preflight OPTIONS; `GZipMiddleware(app, minimum_size=N)` compresses only responses at least N bytes and only when the client sends `Accept-Encoding: gzip`. Preflight responses never carry Content-Encoding (CGI of size, not middleware).
- **Region move checklist (human steps, docs must carry them):** recreate the service in Singapore (Render cannot change region in place) > re-enter all `sync: false` dashboard secrets (DATABASE_URL, CORS_ALLOWED_ORIGINS, IAM_MFA_SECRET_KEY, LANGFUSE pair, SENTRY_DSN, OTEL endpoint/headers/version, GRAFANA_URL, SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, INTAKE_MEDIA_KEY, PROFILE_MEDIA_KEY, AI_API_KEY, AI_BASE_URL, AI_MODEL, AI_ASR_MODEL, AI_PRICING_TABLE, fallback chain, webhook secrets) > re-verify the generated key - `generateValue: true` on GATEWAY_JWT_SIGNING_KEY means a recreated service mints a NEW signing key, so existing sessions are invalid after the move > update the Vercel `NEXT_PUBLIC_API_BASE_URL` to the new service URL > update the `LIVE_BACKEND_URL` repository variable that keep-warm.yml reads > run `npm run check:latency -- --backend-url <new-url> --iterations 20` for the after-number > retire the old service only after that probe exits 0 and one full login + data flow succeeds.
- **Cold starts:** Render free spins the service down after inactivity; keep-warm crons every 10 min, so the region move changes the cron's target, not its schedule. The probe's own warm-up/retry window absorbs one cold start; first-run numbers may still include it.
