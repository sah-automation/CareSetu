// TEST-A2 (#134): warm up the live backend and mint the shared session token
// the live load sweep uses.
//
// The token is minted from the live register -> GET /v1/auth/dev/otp -> verify
// -> session flow on a DEDICATED test phone (TEST_PHONE, default +91
// 9000000002) distinct from the seeded demo phone +91 9000000001, so this job
// never races the live smoke (TEST-D) on the 60 s per-phone resend cooldown.
// A warm-up /health poll runs first to absorb the Render free cold start
// (plan §2, §3.A2). The sweep is a tolerant health check: if this runs right
// after a deploy hook, the old instance may still answer 200s during the
// build, so the warm-up may settle on the previous release - accepted by
// design (tolerant thresholds, no claim of verifying the new build).
//
// Prints ONLY the JWT on stdout; diagnostics go to stderr, so `$(node
// scripts/loadtest/mint-live-token.cjs)` captures just the token.
//
// The auth-surface call count stays low (one register -> read-back -> verify ->
// session per attempt) so the per-IP /v1/auth/* limiter (10 req / 60 s, plan
// §2) is never tripped; a register inside the resend cooldown waits the window
// out before retrying, and a failed attempt paces a full window before the
// next one.
const { setTimeout: sleep } = require("node:timers/promises");

const BASE_URL = process.env.LIVE_BACKEND_URL;
const TEST_PHONE = process.env.TEST_PHONE || "9000000002";
const PHONE_E164 = `+91${TEST_PHONE}`;
const WARMUP_TIMEOUT_MS = 10 * 60 * 1000;
const WARMUP_POLL_MS = 10 * 1000;
const REQUEST_TIMEOUT_MS = 60 * 1000;
const MAX_REGISTER_ATTEMPTS = 5;
const MAX_MINT_ATTEMPTS = 3;
const RETRY_PACING_SECONDS = 65;

if (!BASE_URL) {
  console.error("mint-live-token: LIVE_BACKEND_URL env var is required");
  process.exit(1);
}

async function requestJson(method, path, body) {
  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const code = data && data.code ? data.code : `HTTP ${res.status}`;
    const message = data && data.message ? data.message : code;
    throw new Error(`${method} ${path} -> ${res.status} ${code}: ${message}`);
  }
  return data;
}

async function warmUp() {
  const deadline = Date.now() + WARMUP_TIMEOUT_MS;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${BASE_URL}/health`, {
        signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
      });
      if (res.status === 200) {
        console.error("mint-live-token: warm-up /health answered 200");
        return;
      }
      console.error(
        `mint-live-token: warm-up /health answered ${res.status}; retrying`,
      );
    } catch (err) {
      console.error(`mint-live-token: warm-up attempt failed: ${err.message}`);
    }
    await sleep(WARMUP_POLL_MS);
  }
  throw new Error(
    `live backend did not become healthy within ${WARMUP_TIMEOUT_MS / 1000}s`,
  );
}

async function register() {
  for (let attempt = 1; attempt <= MAX_REGISTER_ATTEMPTS; attempt++) {
    const result = await requestJson("POST", "/v1/auth/register", {
      phone: TEST_PHONE,
    });
    if (result.outcome === "sent") {
      return result;
    }
    if (result.outcome === "cooldown") {
      const wait = (result.cooldown_remaining_seconds ?? 60) + 2;
      console.error(
        `mint-live-token: register in cooldown; waiting ${wait}s (attempt ${attempt})`,
      );
      await sleep(wait * 1000);
      continue;
    }
    throw new Error(`register refused: ${result.outcome}`);
  }
  throw new Error(
    `register still in cooldown after ${MAX_REGISTER_ATTEMPTS} attempts`,
  );
}

async function readOtp() {
  const result = await requestJson(
    "GET",
    `/v1/auth/dev/otp?phone=${encodeURIComponent(PHONE_E164)}`,
  );
  if (typeof result.code !== "string" || result.code === "") {
    throw new Error("dev/otp read-back returned no code (instance swap?)");
  }
  return result.code;
}

async function mintToken() {
  await register();
  const code = await readOtp();
  const verify = await requestJson("POST", "/v1/auth/verify", {
    phone: TEST_PHONE,
    otp: code,
  });
  if (verify.outcome !== "verified") {
    throw new Error(`verify outcome was ${verify.outcome}`);
  }
  const session = await requestJson("POST", "/v1/auth/session", {
    phone: TEST_PHONE,
  });
  if (typeof session.jwt !== "string" || session.jwt === "") {
    throw new Error("session did not mint a JWT");
  }
  return session.jwt;
}

async function main() {
  await warmUp();
  for (let attempt = 1; attempt <= MAX_MINT_ATTEMPTS; attempt++) {
    try {
      const jwt = await mintToken();
      console.log(jwt);
      return;
    } catch (err) {
      console.error(
        `mint-live-token: attempt ${attempt}/${MAX_MINT_ATTEMPTS} failed: ${err.message}`,
      );
      if (attempt < MAX_MINT_ATTEMPTS) {
        // Pace the auth-surface calls: the per-IP limiter caps /v1/auth/* at
        // 10 req / 60 s, and a re-register inside the 60 s cooldown returns
        // "cooldown" (register() waits it out). A full window between attempts
        // keeps every retry under the cap.
        console.error(
          `mint-live-token: waiting ${RETRY_PACING_SECONDS}s before retrying`,
        );
        await sleep(RETRY_PACING_SECONDS * 1000);
      }
    }
  }
  console.error("mint-live-token: failed to mint a live session token");
  process.exit(1);
}

main();
