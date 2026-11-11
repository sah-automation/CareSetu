# #904 before-baseline: deployed backend latency

Captured 2026-11-11, before the #904 frontend data-fetching migration landed.
This is the "before" number for the #904 PR; the "after" run must use the same
command, endpoint list, and threshold.

## Command

```bash
node scripts/py.cjs scripts/measure_backend_latency.py \
  --backend-url https://caresetu-backend.onrender.com --timeout 120
```

## Table

```
endpoint                        n       p50       p95       min       max  server-p95  verdict
----------------------------------------------------------------------------------------------
/health                        10     444.6    2284.7     422.2    3428.7           -     FAIL
/v1/me                         10    1928.1    5629.8    1796.7    5716.2           -     FAIL
/v1/me/profile                 10    1939.9    5657.0    1814.9    5692.4           -     FAIL
- * p95 threshold: 1000.0 ms
latency probe: FAIL (an endpoint breached 1000.0 ms p95)
```

## Notes

- Columns are milliseconds, 10 iterations per endpoint, demo-login bearer minted per run.
- The deployed demo backend (Render free tier, cold start) breaches the 1000 ms
  p95 dev threshold on all three endpoints; the verdict letters are expected for
  this environment and are the record of the starting point, not a gate failure
  of this PR. Frontend-side #904 improvements (dedupe, caching, parallelizing)
  reduce the number of round trips the app pays, which shows up in this probe
  as fewer /v1/me and /v1/me/profile calls per user journey rather than as a
  faster single request.
