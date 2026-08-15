// TEST-A1 (#127): run the k6 patient-flow regression load test.
//
// `npm run test:load` -> this script. Boots the local backend the same way the
// Playwright suite does - migrations then uvicorn on :8000 via
// scripts/e2e-backend.cjs, with the mock SMS adapter and
// GATEWAY_RATE_LIMIT_ENABLED=false (playwright.config.ts's posture) so the
// auth surface is never capped - waits for /health, runs the k6 scenario in
// scripts/loadtest/patient-flow.js, then tears the backend tree down and
// propagates k6's exit code (non-zero when a threshold is breached, zero when
// within bounds).
const { spawn, spawnSync } = require("node:child_process");
const http = require("node:http");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..", "..");
const BACKEND_BOOT_SCRIPT = path.join(ROOT, "scripts", "e2e-backend.cjs");
const SCENARIO = path.join(__dirname, "patient-flow.js");
const BASE_URL = "http://localhost:8000";
const HEALTH_URL = `${BASE_URL}/health`;
const BOOT_TIMEOUT_MS = 120_000;

// Same env posture as playwright.config.ts (the seam A1 was designed to copy):
// mock SMS (never a real provider), gateway JWT verify on so the /v1/me
// admit/deny is real, and the auth rate limiter forced off for this instance
// only - the default posture in config.py is untouched. DATABASE_URL flows
// through from process.env (CI sets it at the job level).
const BACKEND_ENV = {
  ...process.env,
  APP_ENVIRONMENT: "test",
  SMS_PROVIDER: "mock",
  GATEWAY_JWT_VERIFY_ENABLED: "true",
  GATEWAY_JWT_SIGNING_KEY: "e2e-dev-only-signing-key",
  GATEWAY_RATE_LIMIT_ENABLED: "false",
};

function killTree(child) {
  if (child.pid == null) return;
  if (process.platform === "win32") {
    // taskkill /T kills the whole descendant tree (uvicorn is a grandchild).
    spawnSync("taskkill", ["/pid", String(child.pid), "/T", "/F"]);
  } else {
    // The boot child is spawned detached so it leads its own process group.
    try {
      process.kill(-child.pid, "SIGTERM");
    } catch {
      // Already gone - nothing to kill.
    }
  }
}

function waitForHealth(bootExited) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + BOOT_TIMEOUT_MS;
    const poll = () => {
      if (bootExited()) {
        reject(
          new Error("the backend boot script exited before serving /health"),
        );
        return;
      }
      const req = http.get(HEALTH_URL, (res) => {
        res.resume();
        if (res.statusCode === 200) {
          resolve();
        } else if (Date.now() >= deadline) {
          reject(new Error("backend did not become healthy in time"));
        } else {
          setTimeout(poll, 1000);
        }
      });
      req.on("error", () => {
        if (Date.now() >= deadline) {
          reject(new Error("backend did not become healthy in time"));
        } else {
          setTimeout(poll, 1000);
        }
      });
    };
    poll();
  });
}

async function main() {
  const boot = spawn(process.execPath, [BACKEND_BOOT_SCRIPT], {
    cwd: ROOT,
    env: BACKEND_ENV,
    stdio: "inherit",
    detached: process.platform !== "win32",
  });
  const bootExited = () => boot.exitCode !== null;

  try {
    await waitForHealth(bootExited);
  } catch (err) {
    killTree(boot);
    console.error("loadtest: backend failed to boot:", err.message);
    if (boot.exitCode !== null) {
      console.error(
        `loadtest: backend boot script exited with code ${boot.exitCode}`,
      );
    }
    process.exit(1);
  }

  console.log("loadtest: backend healthy; running k6 scenario", SCENARIO);
  const k6 = spawnSync("k6", ["run", SCENARIO, "-e", `BASE_URL=${BASE_URL}`], {
    stdio: "inherit",
    env: process.env,
  });

  killTree(boot);

  if (k6.error) {
    console.error("loadtest: failed to run k6:", k6.error.message);
    console.error(
      "loadtest: install k6 and put it on PATH (this repo uses D:\\Dev\\tools\\bin\\k6.exe; CI installs it explicitly)",
    );
    process.exit(1);
  }
  process.exit(k6.status === null ? 1 : k6.status);
}

main();
