# Backend latency probe (LAT-HARNESS, #901)

The reproducible measurement harness for backend request latency: one command that reports per-endpoint p50/p95/min/max and exits non-zero on a p95 threshold breach. The latency tickets (#902, #903, #904) cite this probe as their before/after verification gate - run it before and after the change, same endpoint list and threshold.

## Run

```bash
# local dev backend (default URL http://localhost:8000, threshold 1000 ms)
npm run check:latency -- --iterations 10

# deployed demo backend, tighter threshold
npm run check:latency -- --backend-url https://<render>.onrender.com --iterations 20 --p95-threshold-ms 2000

# restrict to specific endpoints (repeatable)
npm run check:latency -- --endpoint /health --endpoint /v1/me
```

Stdlib-only script at `scripts/measure_backend_latency.py`; Python-only args work directly too: `node scripts/py.cjs scripts/measure_backend_latency.py --help`.

## Output

```
endpoint                          n       p50       p95       min       max  server-p95  verdict
--------------------------------------------------------------------------------------------
/health                          10      12.3      15.6       9.8      18.2         9.1     PASS
/v1/me                           10      45.1     120.5      33.0     140.2        88.0     PASS
/v1/me/profile                   10      44.9     121.0      32.8     141.0        87.2     PASS
- * p95 threshold: 1000.0 ms
latency probe: PASS (all endpoints within 1000.0 ms p95)
```

- Columns are milliseconds; p50/p95 use linear interpolation (the same convention as the observability rollup's `percentile`).
- `server-p95` appears when the backend answers with the opt-in `Server-Timing: caresetu_tstmp;dur=<ms>` header (`SERVER_TIMING_HEADER_ENABLED`, default on in dev/test, off in production). Total minus server is the network round trip: a high total with a low server figure is the link, not the app.
- An endpoint passes when every response was 2xx AND its p95 is at or under the threshold. A fast 401 is a FAIL, never a pass.

## Exit codes

| Code | Meaning                                                          |
| ---- | ---------------------------------------------------------------- |
| 0    | All endpoints within threshold                                   |
| 1    | At least one endpoint breached the threshold or answered non-2xx |
| 2    | The harness itself failed (connection refused, login failure)    |

Exit code 1 is the gate: a latency ticket's verification step is "probe exits 0 after the change at the same threshold".

## Authentication

Endpoints default to `/health` (unauthenticated) plus `/v1/me` and `/v1/me/profile` (representative authenticated patient reads).

Every non-`/health` endpoint needs a bearer token, resolved in order:

1. `--token` argument
2. `LATENCY_PROBE_TOKEN` environment variable
3. The demo login flow: register a random phone, read the mock OTP back via `GET /v1/auth/dev/otp`, verify, open a session. This needs the backend to run `SMS_PROVIDER=mock` with `APP_ENVIRONMENT` in {dev,test} (or `DEMO_MODE=true`) - exactly the demo posture. Against a deployment without the read-back, pass `--token` explicitly. The random per-run phone avoids the 60 s resend cooldown and the per-phone lockout; `--phone` pins it.

Note: the measured loop never touches the rate-limited `/v1/auth/*` surface - the token is minted once up front (4 auth calls per run, under the 10 req/60 s limiter).

## Cleanup

All instrumentation carries the `caresetu_tstmp` tag plus the `SERVER_TIMING_HEADER_ENABLED` flag (user story 7). Removing the harness is a single grep for either.
