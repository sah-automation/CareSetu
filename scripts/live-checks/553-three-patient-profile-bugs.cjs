#!/usr/bin/env node
"use strict";

/**
 * THROWAWAY OPERATOR DIAGNOSTIC - deliberately NOT a test-suite entry.
 *
 * Ticket #559 (parent #553). Reproduces the three reported `/patient/profile`
 * symptoms against a RUNNING service so a regression is caught by a script
 * rather than by hand:
 *
 *   1. an acknowledged first health-background save answers success, and a
 *      subsequent read reports the acknowledgment;
 *   2. a photo upload's object is present in the PRIVATE profile-media bucket
 *      under the service-role key, not only on local disk;
 *   3. an appended measurement is present in the first page after the list
 *      reloads (already green - this is the guard).
 *
 * It is an EXTERNAL CONSUMER: it speaks HTTP and reads the storage REST API
 * only. It never imports a backend module, so it cannot accidentally agree
 * with the app about a bug it is meant to catch.
 *
 * It is NOT wired into `npm run test:unit:*`, `npm run test:integration`,
 * `npm run test:e2e` or any CI job - it needs a live Supabase project and a
 * running service, which belong in the operator's hands.
 *
 * Usage:
 *   node scripts/live-checks/553-three-patient-profile-bugs.cjs
 *   LIVE_BACKEND_URL=http://localhost:8000 node scripts/live-checks/553-three-patient-profile-bugs.cjs
 *
 * Env (all optional; .env is read as a fallback, process.env wins):
 *   LIVE_BACKEND_URL           default http://localhost:8000
 *   SUPABASE_URL               required for assertion 2
 *   SUPABASE_SERVICE_ROLE_KEY  required for assertion 2
 *   DATABASE_URL               used only for the independent Postgres preflight
 *   PROFILE_MEDIA_BACKEND      reported as a diagnostic; not asserted
 *   PROFILE_MEDIA_ROOT         used for the local-disk cross-check
 *
 * Exit code 0 = every assertion passed, 1 = at least one FAILED,
 * 2 = the loop never reached the assertions (environment untrustworthy, or no
 * patient session could be established).
 *
 * An assertion that could not be EVALUATED is reported SKIP, never FAIL: an
 * unreadable bucket is not a storage regression, and only a real FAIL means the
 * product changed.
 */

const crypto = require("node:crypto");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");
const zlib = require("node:zlib");

const ROOT = path.resolve(__dirname, "..", "..");
const BACKEND_DIR = path.join(ROOT, "apps", "backend");

const BACKEND_URL = (
  process.env.LIVE_BACKEND_URL || "http://localhost:8000"
).replace(/\/+$/, "");
const REQUEST_TIMEOUT_MS = 30_000;
const MEDIA_BUCKET = "profile-media";
const ACK_REQUIRED_CODE = "HEALTH_BACKGROUND_ACK_REQUIRED";
const NATIVE_PHONE_PREFIX = "+91";

/**
 * A stored profile photo is AES-256-GCM: a 12-byte nonce, the ciphertext, and
 * a 16-byte tag. Even an empty payload therefore occupies 28 bytes, so an
 * object at or below that size is a truncated write rather than a stored photo.
 */
const AES_GCM_EMPTY_FRAME_BYTES = 12 + 16;

// ---------------------------------------------------------------------------
// Reporting. Each assertion prints its own block so a partial failure says
// WHICH symptom regressed.
// ---------------------------------------------------------------------------

const results = [];

function banner(text) {
  console.log("");
  console.log("=".repeat(72));
  console.log(text);
  console.log("=".repeat(72));
}

function step(text) {
  console.log(`  - ${text}`);
}

function ok(text) {
  console.log(`    ok   ${text}`);
}

function note(text) {
  console.log(`    note ${text}`);
}

/** A condition that will stop one assertion from running, without aborting. */
function warn(text) {
  console.log(`    warn ${text}`);
}

/** Reasons A2 could not run, decided by the preflight and consumed by A2. */
let a2Blockers = [];

function beginAssertion(id, title) {
  banner(`ASSERTION ${id} - ${title}`);
}

function pass(id, detail) {
  results.push({ id, status: "PASS", detail });
  console.log(`  => ${id} PASS${detail ? `: ${detail}` : ""}`);
}

function fail(id, detail) {
  results.push({ id, status: "FAIL", detail });
  console.log(`  => ${id} FAIL: ${detail}`);
}

/**
 * An assertion that could not be evaluated. Kept distinct from FAIL on
 * purpose: "the script could not look" is not "the product regressed", and
 * collapsing the two would let an environment problem read as a symptom.
 */
function skip(id, detail) {
  results.push({ id, status: "SKIP", detail });
  console.log(`  => ${id} SKIP: ${detail}`);
}

function summarise() {
  banner("SUMMARY");
  for (const r of results) {
    console.log(`  ${r.status.padEnd(4)}  ${r.id}  ${r.detail}`);
  }
  const failed = results.filter((r) => r.status === "FAIL");
  const skipped = results.filter((r) => r.status === "SKIP");
  console.log("");
  if (failed.length === 0 && skipped.length === 0) {
    console.log(`  All ${results.length} assertions passed.`);
  } else {
    if (failed.length > 0) {
      console.log(
        `  ${failed.length} of ${results.length} assertions failed: ${failed
          .map((r) => r.id)
          .join(", ")}`,
      );
    }
    if (skipped.length > 0) {
      console.log(
        `  ${skipped.length} could not be evaluated (not a regression): ${skipped
          .map((r) => r.id)
          .join(", ")}`,
      );
    }
  }
  return failed.length === 0 ? 0 : 1;
}

// ---------------------------------------------------------------------------
// Preflight. Checks PostgreSQL connectivity INDEPENDENTLY of the integration
// suite, because the integration suite is red on the untouched tree for an
// unrelated schema-bootstrap reason and must not block this loop.
// ---------------------------------------------------------------------------

function readDotEnv(file) {
  const out = {};
  let text;
  try {
    text = fs.readFileSync(file, "utf8");
  } catch {
    return out;
  }
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (line === "" || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq < 1) continue;
    const key = line.slice(0, eq).trim();
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"') && value.length > 1) ||
      (value.startsWith("'") && value.endsWith("'") && value.length > 1)
    ) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

const dotEnv = readDotEnv(path.join(ROOT, ".env"));

/** process.env wins over .env - the backend resolves them the same way. */
function setting(name, fallback) {
  const fromProcess = process.env[name];
  if (fromProcess !== undefined && fromProcess !== "") return fromProcess;
  const fromFile = dotEnv[name];
  if (fromFile !== undefined && fromFile !== "") return fromFile;
  return fallback;
}

/**
 * A connection URL reduced to its scheme and host. Used on the one error path
 * that has to talk about a URL which may carry a password: the credential is
 * dropped rather than masked, because there is no reason to echo any part of
 * it. Falls back to a shape-only description when the URL will not parse.
 */
function redactUrl(raw) {
  try {
    const parsed = new URL(raw.replace(/^[a-z+]+:\/\//, "http://"));
    const scheme = raw.slice(0, raw.indexOf("://"));
    return `${scheme}://${parsed.hostname}${parsed.port ? `:${parsed.port}` : ""}`;
  } catch {
    return `${raw.length} chars, unparseable`;
  }
}

function probeTcp(host, port, timeoutMs = 5_000) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    const done = (reachable, detail) => {
      socket.destroy();
      resolve({ reachable, detail });
    };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => done(true, `connected to ${host}:${port}`));
    socket.once("timeout", () =>
      done(false, `timed out reaching ${host}:${port}`),
    );
    socket.once("error", (err) =>
      done(false, `${host}:${port} -> ${err.code || err.message}`),
    );
    socket.connect(port, host);
  });
}

function preflightFatal(problems) {
  banner("PREFLIGHT FAILED");
  for (const p of problems) console.log(`  x ${p}`);
  console.log("");
  console.log(
    "  The environment could not be established, so any red below would be a\n" +
      "  false negative. Fix the above first.",
  );
  return 2;
}

async function preflight() {
  banner("PREFLIGHT");
  const problems = [];

  // 1. The running service.
  let backendOk = false;
  try {
    const res = await fetch(`${BACKEND_URL}/health`, {
      signal: AbortSignal.timeout(10_000),
    });
    backendOk = res.status === 200;
    if (backendOk) ok(`backend serving /health at ${BACKEND_URL}`);
    else problems.push(`backend /health answered ${res.status} (want 200)`);
  } catch (err) {
    problems.push(
      `backend not reachable at ${BACKEND_URL} (${err.message}). ` +
        "Boot it with: node scripts/e2e-backend.cjs",
    );
  }

  // 2. PostgreSQL, independently of the integration suite.
  const databaseUrl = setting("DATABASE_URL", "");
  if (!databaseUrl) {
    problems.push("DATABASE_URL is not set in the environment or .env");
  } else {
    let host = "localhost";
    let port = 5432;
    let parseable = true;
    try {
      const parsed = new URL(databaseUrl.replace(/^[a-z+]+:\/\//, "http://"));
      host = parsed.hostname || host;
      port = Number(parsed.port || 5432);
    } catch {
      parseable = false;
      // Never print the raw value: a DATABASE_URL carries the role's password
      // (security-phii-standards.md §4 - credentials never reach logs).
      problems.push(
        "DATABASE_URL is set but is not a parseable URL " +
          `(scheme + host only: ${redactUrl(databaseUrl)})`,
      );
    }
    if (parseable) {
      const probe = await probeTcp(host, port);
      if (probe.reachable) ok(`postgres reachable: ${probe.detail}`);
      else problems.push(`postgres unreachable: ${probe.detail}`);
    }
  }

  // 3. Supabase + the service-role key, needed to look inside the bucket.
  //    Only A2 needs these, so a problem here downgrades A2 to SKIPPED rather
  //    than aborting the run and losing the A1 and A3 signal, which are pure
  //    HTTP against the service and stay meaningful without Supabase.
  const supabaseUrl = (setting("SUPABASE_URL", "") || "").replace(/\/+$/, "");
  const serviceRoleKey = setting("SUPABASE_SERVICE_ROLE_KEY", "");
  const blockers = [];
  if (!supabaseUrl) {
    blockers.push("SUPABASE_URL is not set");
  }
  if (!serviceRoleKey) {
    blockers.push("SUPABASE_SERVICE_ROLE_KEY is not set");
  }
  if (blockers.length > 0) {
    a2Blockers = blockers.map(
      (b) => `${b} - assertion 2 cannot look in the bucket`,
    );
    for (const b of a2Blockers) warn(b);
  } else {
    try {
      const res = await fetch(
        `${supabaseUrl}/storage/v1/bucket/${MEDIA_BUCKET}`,
        {
          headers: { Authorization: `Bearer ${serviceRoleKey}` },
          signal: AbortSignal.timeout(15_000),
        },
      );
      if (res.ok) {
        ok(`supabase reachable; private bucket "${MEDIA_BUCKET}" exists`);
        // Only a 2xx here means the service-role key is ACCEPTED, which is what
        // makes A2's object lookup trustworthy. Anything else leaves the loop
        // unable to tell a rejected credential from a missing object, and a
        // guess either way would be a fabricated symptom.
      } else {
        a2Blockers = [
          `the service-role key was not accepted for bucket "${MEDIA_BUCKET}" ` +
            `(HTTP ${res.status}), so A2 cannot tell a rejected credential apart ` +
            "from an absent object",
        ];
        warn(a2Blockers[0]);
      }
    } catch (err) {
      a2Blockers = [
        `supabase not reachable at ${redactUrl(supabaseUrl)} (${err.message}) - ` +
          "assertion 2 cannot read the bucket",
      ];
      warn(a2Blockers[0]);
    }
  }

  // 4. Diagnostics, not gates. These report THIS script's environment, which
  // is the local .env - NOT the environment the running service booted with.
  // When LIVE_BACKEND_URL points at another instance the two can disagree, and
  // A2 is the assertion that settles it either way.
  step(
    `this process: PROFILE_MEDIA_BACKEND = ${setting(
      "PROFILE_MEDIA_BACKEND",
      "(unset -> local)",
    )}`,
  );
  step(
    `this process: PROFILE_MEDIA_KEY    = ${setting("PROFILE_MEDIA_KEY", "") ? "set" : "(unset -> ephemeral per-process)"}`,
  );
  if (dotEnv.SUPABASE_SERVICE_ROLE_KEY) {
    note("service-role key read from .env; its value is never printed");
  }

  return { problems, supabaseUrl, serviceRoleKey, a2Blockers };
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

/**
 * `binary` returns the response as a byte count instead of parsing it. Used
 * for the storage probe: the object is AES-256-GCM ciphertext, and printing it
 * as a "non-JSON body" would be unreadable noise in the middle of the report.
 */
async function call(method, url, { bearer, body, headers, raw, binary } = {}) {
  const init = {
    method,
    headers: { Accept: "application/json", ...(headers || {}) },
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  };
  if (bearer) init.headers.Authorization = `Bearer ${bearer}`;
  if (raw) {
    init.body = raw;
  } else if (body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  const res = await fetch(url, init);
  if (binary) {
    const buf = await res.arrayBuffer();
    return {
      status: res.status,
      ok: res.ok,
      byteLength: buf.byteLength,
      data: null,
      text: null,
    };
  }
  const text = await res.text();
  let data = null;
  if (text !== "") {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  return { status: res.status, ok: res.ok, data, text, byteLength: null };
}

function describe(result) {
  if (result.data === null) return `HTTP ${result.status} (empty body)`;
  if (typeof result.data === "string") {
    return `HTTP ${result.status} non-JSON body: ${result.data.slice(0, 200)}`;
  }
  const code = result.data && result.data.code ? ` ${result.data.code}` : "";
  const message =
    result.data && result.data.message ? `: ${result.data.message}` : "";
  return `HTTP ${result.status}${code}${message}`;
}

/**
 * A fresh 10-digit national number per run, leading 9 to match the convention
 * the repo's other register-driven scripts use. Never reuse an identity: a
 * leftover acknowledgment from a prior run would mask the first-save behaviour
 * assertion 1 is trying to observe.
 */
function randomPhone() {
  const remaining = Array.from({ length: 9 }, () =>
    Math.floor(Math.random() * 10),
  ).join("");
  return `9${remaining}`;
}

function idempotencyKey() {
  return crypto.randomUUID();
}

// ---------------------------------------------------------------------------
// Register -> OTP read-back -> verify -> session, reusing the repo's existing
// conventions (scripts/loadtest/mint-live-token.cjs, scripts/live_smoke.py).
// ---------------------------------------------------------------------------

async function registerPatient(phone) {
  const register = await call("POST", `${BACKEND_URL}/v1/auth/register`, {
    body: { phone },
  });
  if (!register.ok) {
    throw new Error(`register -> ${describe(register)}`);
  }
  const outcome = register.data && register.data.outcome;
  if (outcome === "cooldown") {
    const wait = (register.data.cooldown_remaining_seconds || 60) + 2;
    throw new Error(
      `register -> cooldown for ${phone}; wait ${wait}s or run with a fresh number ` +
        "(a leftover cooldown from a prior run is not a product defect)",
    );
  }
  if (outcome !== "sent") {
    throw new Error(
      `register -> unexpected outcome ${JSON.stringify(outcome)}`,
    );
  }

  const otpQuery = `phone=${encodeURIComponent(NATIVE_PHONE_PREFIX + phone)}`;
  const otp = await call("GET", `${BACKEND_URL}/v1/auth/dev/otp?${otpQuery}`);
  if (!otp.ok) {
    throw new Error(
      `dev/otp read-back -> ${describe(otp)}. The read-back needs SMS_PROVIDER=mock ` +
        "and APP_ENVIRONMENT in {dev,test} (or DEMO_MODE=true).",
    );
  }
  const code = otp.data && otp.data.code;
  if (typeof code !== "string" || code === "") {
    throw new Error("dev/otp read-back returned no code");
  }

  const verify = await call("POST", `${BACKEND_URL}/v1/auth/verify`, {
    body: { phone, otp: code },
  });
  if (!verify.ok) {
    throw new Error(`verify -> ${describe(verify)}`);
  }
  if (!verify.data || verify.data.outcome !== "verified") {
    throw new Error(
      `verify -> unexpected outcome ${JSON.stringify(verify.data)}`,
    );
  }

  const session = await call("POST", `${BACKEND_URL}/v1/auth/session`, {
    body: { phone },
  });
  if (!session.ok) {
    throw new Error(`session -> ${describe(session)}`);
  }
  const jwt = session.data && session.data.jwt;
  if (typeof jwt !== "string" || jwt === "") {
    throw new Error("session -> no jwt");
  }

  const me = await call("GET", `${BACKEND_URL}/v1/me`, { bearer: jwt });
  if (!me.ok) {
    throw new Error(`/v1/me -> ${describe(me)}`);
  }
  const roles = me.data && me.data.roles;
  if (!Array.isArray(roles) || !roles.includes("patient")) {
    throw new Error(
      `/v1/me -> roles ${JSON.stringify(roles)} (want a patient)`,
    );
  }
  return { jwt, subjectId: me.data.subject_id };
}

// ---------------------------------------------------------------------------
// A real PNG, built rather than embedded, so the upload is a genuine image the
// backend's media sniff accepts.
// ---------------------------------------------------------------------------

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c;
  }
  return table;
})();

function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i += 1)
    c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function pngChunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const typeAndData = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(typeAndData), 0);
  return Buffer.concat([length, typeAndData, crc]);
}

function buildPng(size) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 2; // colour type: truecolour
  const raw = Buffer.alloc(size * (1 + size * 3));
  for (let y = 0; y < size; y += 1) {
    const rowStart = y * (1 + size * 3);
    raw[rowStart] = 0; // filter: none
    for (let x = 0; x < size; x += 1) {
      const p = rowStart + 1 + x * 3;
      raw[p] = (x * 4) % 256;
      raw[p + 1] = (y * 4) % 256;
      raw[p + 2] = 0x80;
    }
  }
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    pngChunk("IHDR", ihdr),
    pngChunk("IDAT", zlib.deflateSync(raw)),
    pngChunk("IEND", Buffer.alloc(0)),
  ]);
}

// ---------------------------------------------------------------------------
// Assertions
// ---------------------------------------------------------------------------

/**
 * Assertion 1 - the acknowledged first health-background save.
 *
 * A fresh patient has never saved, so this IS the first save and it carries
 * `acknowledge_phi: true`. It must answer success. The interesting failure is
 * a genuine 500 from an int() coercion one layer below the route, so this
 * asserts on the RESPONSE - success, and specifically neither the ack-required
 * code nor a 5xx - rather than on a code the facade was supposed to translate.
 */
async function assertion1(jwt) {
  beginAssertion(
    1,
    "acknowledged first health-background save answers success, and the read reports it",
  );

  const background = {
    blood_group: "O+",
    conditions: ["none reported"],
    allergies: [],
    medications: [],
    immunizations: [],
    family_history: [],
  };

  const save = await call("PUT", `${BACKEND_URL}/v1/me/health-background`, {
    bearer: jwt,
    headers: { "Idempotency-Key": idempotencyKey() },
    body: { acknowledge_phi: true, background },
  });
  step(
    `PUT /v1/me/health-background (acknowledge_phi: true) -> ${describe(save)}`,
  );

  if (save.status >= 500) {
    fail(
      "A1",
      `the acknowledged first save answered a server error (${describe(save)}). ` +
        "This is the reported symptom: the save 500s instead of succeeding.",
    );
    return;
  }
  if (save.data && save.data.code === ACK_REQUIRED_CODE) {
    fail(
      "A1",
      `the acknowledged first save answered ${ACK_REQUIRED_CODE} (${describe(save)}). ` +
        "Acknowledging was requested, so this code must not appear.",
    );
    return;
  }
  if (!save.ok) {
    fail(
      "A1",
      `the acknowledged first save did not succeed: ${describe(save)}`,
    );
    return;
  }
  ok("the acknowledged first save answered success");

  const read = await call("GET", `${BACKEND_URL}/v1/me/health-background`, {
    bearer: jwt,
  });
  step(`GET /v1/me/health-background -> ${describe(read)}`);
  if (!read.ok) {
    fail("A1", `the read after the save did not succeed: ${describe(read)}`);
    return;
  }
  const view = read.data || {};
  if (view.acknowledged !== true) {
    fail(
      "A1",
      `the save succeeded but the subsequent read reports acknowledged=${JSON.stringify(
        view.acknowledged,
      )} (want true).`,
    );
    return;
  }
  if (view.set !== true) {
    fail("A1", `the read reports set=${JSON.stringify(view.set)} (want true)`);
    return;
  }
  const stored = view.background || {};
  if (stored.blood_group !== background.blood_group) {
    fail(
      "A1",
      `the snapshot did not round-trip: blood_group=${JSON.stringify(
        stored.blood_group,
      )} (want ${JSON.stringify(background.blood_group)})`,
    );
    return;
  }
  ok("the read reports acknowledged=true and the snapshot round-tripped");
  pass(
    "A1",
    "acknowledged first save answered success; the read reports the acknowledgment",
  );
}

/**
 * Assertion 2 - durable photo storage.
 *
 * A 200 from the upload endpoint does NOT prove durable storage, and neither
 * does finding the file on local disk. This looks the object up in the PRIVATE
 * profile-media bucket under the service-role key, which is the only check
 * that distinguishes #555's fix from the reported symptom.
 */
async function assertion2(jwt, supabaseUrl, serviceRoleKey) {
  beginAssertion(
    2,
    "the uploaded photo's object is in the private profile-media bucket under the service-role key",
  );

  // A credential the bucket will not accept means this assertion cannot be
  // evaluated. Reporting that as a storage regression would be a false red on
  // the very check that is easiest to fake, so it is a SKIP.
  if (a2Blockers.length > 0) {
    skip("A2", a2Blockers.join("; "));
    return;
  }

  const png = buildPng(64);

  // Precondition, not the symptom: the photo surface is refused with
  // PROFILE_NOT_SET until the profile row exists. Reported separately so a
  // precondition failure is never mistaken for the bucket regression.
  const profileWrite = await call("PUT", `${BACKEND_URL}/v1/me/profile`, {
    bearer: jwt,
    headers: { "Idempotency-Key": idempotencyKey() },
    body: {
      name: "Loop Probe",
      age: 30,
      gender: "female",
      preferred_language: "en",
      area: null,
      emergency_contact: null,
      photo_ref: null,
    },
  });
  step(`PUT /v1/me/profile (precondition) -> ${describe(profileWrite)}`);
  if (
    !profileWrite.ok ||
    !profileWrite.data ||
    profileWrite.data.set !== true
  ) {
    fail(
      "A2",
      `PRECONDITION not met, so the upload was never attempted: ${describe(
        profileWrite,
      )}. ` +
        "The photo endpoint refuses PROFILE_NOT_SET until the profile row exists. " +
        "This is a gap in the loop, not the reported symptom.",
    );
    return;
  }
  ok("the patient profile exists, so the photo endpoint will accept an upload");

  const form = new FormData();
  form.append("file", new Blob([png], { type: "image/png" }), "probe.png");
  const upload = await call("PUT", `${BACKEND_URL}/v1/me/photo`, {
    bearer: jwt,
    headers: { "Idempotency-Key": idempotencyKey() },
    raw: form,
  });
  step(
    `PUT /v1/me/photo (multipart, field "file", ${png.length} bytes) -> ${describe(upload)}`,
  );

  if (!upload.ok) {
    fail("A2", `the photo upload did not succeed: ${describe(upload)}`);
    return;
  }
  const profile = upload.data && upload.data.profile;
  const photoRef = profile && profile.photo_ref;
  if (typeof photoRef !== "string" || photoRef === "") {
    fail(
      "A2",
      "the upload succeeded but answered no profile.photo_ref to look up",
    );
    return;
  }
  ok(`the upload answered photo_ref = ${photoRef}`);

  const objectUrl = `${supabaseUrl}/storage/v1/object/${MEDIA_BUCKET}/${photoRef}`;
  const lookup = await call("GET", objectUrl, {
    bearer: serviceRoleKey,
    binary: true,
  });
  step(
    `GET /storage/v1/object/${MEDIA_BUCKET}/${photoRef} (service role) -> ` +
      `HTTP ${lookup.status}, ${lookup.byteLength} bytes of ciphertext`,
  );

  // Local-disk cross-check: a diagnostic, not the assertion. With the local
  // backend active this file is the false positive the ticket warns about.
  const mediaRoot = setting(
    "PROFILE_MEDIA_ROOT",
    path.join("var", "profile-media"),
  );
  const onDisk = fs.existsSync(path.join(BACKEND_DIR, mediaRoot, photoRef));
  note(
    `on local disk under apps/backend/${mediaRoot}: ${onDisk ? "yes (not evidence of durability)" : "no"}`,
  );

  if (!lookup.ok) {
    // The preflight already established that this key is accepted, so a
    // non-2xx here is the object genuinely not being there - the symptom.
    fail(
      "A2",
      `the object is NOT in the private "${MEDIA_BUCKET}" bucket (HTTP ${lookup.status}). ` +
        "The photo exists only outside durable storage - this is the reported symptom.",
    );
    return;
  }
  if (!lookup.byteLength) {
    fail(
      "A2",
      `the bucket answered HTTP ${lookup.status} but returned zero bytes, so nothing was stored`,
    );
    return;
  }
  if (lookup.byteLength <= AES_GCM_EMPTY_FRAME_BYTES) {
    fail(
      "A2",
      `the bucket object is ${lookup.byteLength} bytes, too short to be an ` +
        "AES-256-GCM frame - the media did not land intact",
    );
    return;
  }
  ok(
    `the object is in the private "${MEDIA_BUCKET}" bucket under the service-role key ` +
      `(${lookup.byteLength} bytes of ciphertext, AES-256-GCM framed)`,
  );
  pass("A2", `object ${photoRef} is in the private ${MEDIA_BUCKET} bucket`);
}

/**
 * Assertion 3 - the series guard.
 *
 * This one is expected to be GREEN already; it guards the landed fix against
 * regressing. If it goes red, something broke.
 */
async function assertion3(jwt) {
  beginAssertion(
    3,
    "an appended measurement is present in the first page after the list reloads",
  );

  const height = 170;
  const weight = 68.5;
  const recordedAt = new Date().toISOString();

  const append = await call(
    "POST",
    `${BACKEND_URL}/v1/me/health-background/metrics`,
    {
      bearer: jwt,
      headers: { "Idempotency-Key": idempotencyKey() },
      body: { height_cm: height, weight_kg: weight, recorded_at: recordedAt },
    },
  );
  step(
    `POST /v1/me/health-background/metrics (height ${height}, weight ${weight}) -> ${describe(append)}`,
  );
  if (!append.ok) {
    fail("A3", `the measurement append did not succeed: ${describe(append)}`);
    return;
  }
  const entryId = append.data && append.data.entry_id;
  ok(`the append answered entry_id = ${JSON.stringify(entryId)}`);

  // The list reload, read from scratch - the same first page the UI calls.
  const list = await call(
    "GET",
    `${BACKEND_URL}/v1/me/health-background/metrics?page=1`,
    {
      bearer: jwt,
    },
  );
  step(`GET /v1/me/health-background/metrics?page=1 -> ${describe(list)}`);
  if (!list.ok) {
    fail("A3", `the first-page read did not succeed: ${describe(list)}`);
    return;
  }
  const items = list.data && list.data.items;
  if (!Array.isArray(items)) {
    fail(
      "A3",
      `the first page answered no items array: ${JSON.stringify(list.data)}`,
    );
    return;
  }
  if (items.length === 0) {
    fail(
      "A3",
      `the first page is empty after the append (total=${JSON.stringify(
        list.data.total,
      )}) - the reported symptom, and a regression of the landed fix.`,
    );
    return;
  }
  if (entryId === undefined || entryId === null) {
    fail(
      "A3",
      "the append succeeded but answered no entry_id, so the read-back cannot be " +
        "matched to the row that was written",
    );
    return;
  }
  // Match on the server-minted id ONLY. Falling back to matching on the
  // height/weight values would let a pre-existing row with the same numbers
  // satisfy the check, which is precisely the "it passed but proved nothing"
  // failure mode this assertion exists to rule out.
  const found = items.find((item) => item.entry_id === entryId);
  if (!found) {
    fail(
      "A3",
      `the first page has ${items.length} item(s) but not the appended one ` +
        `(entry_id=${JSON.stringify(entryId)}); items=${JSON.stringify(items)}`,
    );
    return;
  }
  if (found.height_cm !== height || found.weight_kg !== weight) {
    fail(
      "A3",
      `entry ${entryId} came back with the wrong values: height_cm=${JSON.stringify(
        found.height_cm,
      )} weight_kg=${JSON.stringify(found.weight_kg)} ` +
        `(want ${height} / ${weight})`,
    );
    return;
  }
  ok(
    `the appended measurement (entry_id ${entryId}) is present in the first page`,
  );
  pass(
    "A3",
    "the appended measurement is in the first page after the list reloads",
  );
}

// ---------------------------------------------------------------------------

async function main() {
  const { problems, supabaseUrl, serviceRoleKey } = await preflight();
  if (problems.length > 0) return preflightFatal(problems);

  const phone = randomPhone();
  banner("THROWAWAY PATIENT");
  step(`phone = ${NATIVE_PHONE_PREFIX}${phone} (fresh identity for this run)`);

  let session;
  try {
    session = await registerPatient(phone);
  } catch (err) {
    // Deliberately NOT routed through preflightFatal: the environment WAS
    // established, the service just would not issue a session. Labelling a
    // service-side failure "the environment could not be established" would
    // send an operator chasing the wrong thing.
    banner("NO SESSION");
    console.log(
      `  x the register / OTP read-back / verify / session sequence failed:`,
    );
    console.log(`      ${err.message}`);
    console.log("");
    console.log(
      "  None of the three symptoms could be exercised, because each one needs a\n" +
        "  patient session. This is NOT a pass and NOT a symptom regression - the\n" +
        "  loop never reached the assertions.",
    );
    return 2;
  }
  ok(`session established; subject_id = ${JSON.stringify(session.subjectId)}`);

  // Assertion 1 runs first, and must: it only observes the FIRST-save grant
  // while the identity is genuinely new.
  const assertions = [
    ["A1", assertion1],
    ["A2", assertion2],
    ["A3", assertion3],
  ];
  for (const [id, assertion] of assertions) {
    try {
      await assertion(session.jwt, supabaseUrl, serviceRoleKey);
    } catch (err) {
      // A thrown assertion is a failure of that assertion alone; the others
      // still run so a partial failure stays legible.
      fail(id, `threw: ${err.message}`);
    }
  }

  return summarise();
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (err) => {
    console.error("the loop itself failed:", err);
    process.exitCode = 2;
  },
);
