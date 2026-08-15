// TEST-A1 (#127) - CI regression load test: the full patient flow in k6.
//
// Drives register -> GET /v1/auth/dev/otp -> verify -> POST /v1/auth/session ->
// GET /v1/me against a locally-booted backend with a throwaway Postgres, the
// mock SMS adapter, and GATEWAY_RATE_LIMIT_ENABLED=false (the same posture
// playwright.config.ts uses), so the auth surface is never capped during the
// ramp. Ramp 10 -> 50 VUs; the in-process mock SMS adapter means each VU reads
// its own OTP over the HTTP dev/otp read-back with its own phone - never a
// shared phone, never a fixed OTP.
//
// The thresholds below are CI-hardware REGRESSION BOUNDS, not product SLAs
// (test-suite plan §3.A1): they guard a PR from slowing the auth surface on a
// fresh GitHub runner, and are deliberately looser than the IAM latency SLAs
// in the whitebox docs (validate_token p95 < 100 ms, verify_otp p95 < 400 ms).
// The backend opens one DB connection per request (NullPool in app/main.py),
// so a Windows dev box whose local Postgres pays a large per-connection setup
// cost can breach the latency bounds here while Linux CI passes - CI is the
// source of truth for this gate; a local breach on such a machine is expected
// and not a failure of the scenario.
//   http_req_failed      rate < 0.01   (errors < 1%)
//   flow_failures        rate < 0.01   (logically-broken flows < 1%)
//   http_req_duration    p(95) < 800   (p95 < 800 ms)
//   http_req_duration    p(99) < 1500  (p99 < 1.5 s)
//
// Run with `npm run test:load`, which boots the local instance, runs this
// scenario, and tears the instance down (scripts/loadtest/run.cjs). k6 is not
// pre-installed on GitHub runners: ci.yml installs it explicitly, the same
// explicit-install treatment as ZAP's JRE step in TEST-B1.
import http from "k6/http";
import { check } from "k6";
import { Rate } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";

const flowFailures = new Rate("flow_failures");

export const options = {
  scenarios: {
    patient_flow: {
      executor: "ramping-vus",
      startVUs: 10,
      stages: [
        { duration: "30s", target: 10 },
        { duration: "30s", target: 50 },
        { duration: "30s", target: 50 },
        { duration: "10s", target: 0 },
      ],
      gracefulRampDown: "5s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<800", "p(99)<1500"],
    flow_failures: ["rate<0.01"],
  },
};

// One unique phone per (VU, iteration): a 10-digit Indian mobile number
// starting with 9. The ramp is monotonic so a VU number is never reused and
// every iteration mints a fresh number - the flow never trips the 60 s resend
// cooldown or the brute-force lockout. RUN_SALT is minted in k6 init and
// differs across runs, so re-running the scenario within 60 s (against the
// persistent local Postgres, the non-CI default) still uses fresh phones
// instead of re-triggering the cooldown on the previous run's numbers.
const RUN_SALT = String(Math.floor(Math.random() * 100)).padStart(2, "0");

function patientPhone() {
  const vu = String(__VU).padStart(3, "0");
  const iteration = String(__ITER).padStart(4, "0");
  return `9${vu}${RUN_SALT}${iteration}`;
}

export default function () {
  const phone = patientPhone();
  const headers = { "Content-Type": "application/json" };

  let flowOk = true;

  const register = http.post(
    `${BASE_URL}/v1/auth/register`,
    JSON.stringify({ phone }),
    { headers },
  );
  flowOk =
    check(register, {
      "register answered 200": (r) => r.status === 200,
      "register issued an OTP challenge": (r) => r.json().outcome === "sent",
    }) && flowOk;

  const otpResponse = http.get(
    `${BASE_URL}/v1/auth/dev/otp?phone=${encodeURIComponent(`+91${phone}`)}`,
  );
  const otp = otpResponse.json().code;
  flowOk =
    check(otpResponse, {
      "OTP read-back answered 200": (r) => r.status === 200,
      "OTP read-back returned the mock code": () => typeof otp === "string",
    }) && flowOk;

  const verify = http.post(
    `${BASE_URL}/v1/auth/verify`,
    JSON.stringify({ phone, otp }),
    { headers },
  );
  flowOk =
    check(verify, {
      "verify answered 200": (r) => r.status === 200,
      "verify outcome is verified": (r) => r.json().outcome === "verified",
    }) && flowOk;

  const session = http.post(
    `${BASE_URL}/v1/auth/session`,
    JSON.stringify({ phone }),
    { headers },
  );
  const jwt = session.json().jwt;
  flowOk =
    check(session, {
      "session answered 200": (r) => r.status === 200,
      "session minted an access JWT": () => typeof jwt === "string",
    }) && flowOk;

  const me = http.get(`${BASE_URL}/v1/me`, {
    headers: { Authorization: `Bearer ${jwt}` },
  });
  flowOk =
    check(me, {
      "/v1/me answered 200": (r) => r.status === 200,
      "/v1/me resolved the patient role": (r) =>
        Array.isArray(r.json().roles) && r.json().roles.includes("patient"),
    }) && flowOk;

  flowFailures.add(!flowOk);
}
