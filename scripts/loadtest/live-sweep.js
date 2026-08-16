// TEST-A2 (#134) - tolerant live production-stack health sweep.
//
// Runs against the live backend (LIVE_BACKEND_URL) after deploy-render:
// 20 VUs for 90 s targeting only the non-rate-limited surface - /health and
// /v1/me (the per-IP auth limiter makes hammering /v1/auth/* meaningless -
// test-suite plan §2, §3.A2). A warm-up request runs first in the job (Render
// free cold start), then the sweep below shares the single session token
// minted by scripts/loadtest/mint-live-token.cjs for a dedicated test phone
// (distinct from the seeded demo phone +91 9000000001).
//
// The thresholds below are TOLERANT health-sweep bounds, NOT product SLAs
// (plan §3.A2): they absorb free-tier shared CPU and cold-start spikes. This
// is a production-stack health sweep, not a capacity test.
//   http_req_failed      rate < 0.02   (errors < 2%)
//   sweep_failures       rate < 0.02   (logically-broken sweeps < 2%)
//   http_req_duration    p(95) < 2500  (p95 < 2.5 s)
//
// The k6 binary is not pre-installed on GitHub runners: the deploy.yml A2 job
// installs it explicitly (same explicit-install treatment as the ci.yml
// load-test job in TEST-A1) and uploads the report as a run artifact.
import http from "k6/http";
import { check } from "k6";
import { Rate } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL;
const TOKEN = __ENV.TOKEN;

const sweepFailures = new Rate("sweep_failures");

export const options = {
  scenarios: {
    live_sweep: {
      executor: "constant-vus",
      vus: 20,
      duration: "90s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.02"],
    http_req_duration: ["p(95)<2500"],
    sweep_failures: ["rate<0.02"],
  },
};

export default function () {
  let ok = true;

  const health = http.get(`${BASE_URL}/health`);
  ok =
    check(health, {
      "/health answered 200": (r) => r.status === 200,
    }) && ok;

  const me = http.get(`${BASE_URL}/v1/me`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
  });
  // Parse defensively: a 200 with a broken body must count as a failed sweep
  // (non-JSON or a missing roles field), not escape every gate because the
  // check callback throws before sweepFailures.add runs.
  let meRoles = [];
  try {
    meRoles = me.json().roles ?? [];
  } catch {
    meRoles = [];
  }
  ok =
    check(me, {
      "/v1/me answered 200": (r) => r.status === 200,
      "/v1/me resolved the patient role": () => meRoles.includes("patient"),
    }) && ok;

  sweepFailures.add(!ok);
}
