// Boots the CareSetu backend for the Playwright E2E suite: applies the schema
// migration, seeds the idempotent demo bootstrap (operator MFA for the
// doctor-workspace spec), then serves the API on :8000. Playwright's webServer
// entry runs this command; the config's `env` sets APP_ENVIRONMENT=test,
// SMS_PROVIDER=mock and enables the gateway JWT verify so the protected-route
// denial is real.
//
// The command must work on both machines that run the suite:
//   - locally the backend-env venv is invoked directly (same resolution as
//     scripts/py.cjs),
//   - in CI the backend is installed via `uv sync --project apps/backend` and
//     `uv run --directory apps/backend` is the correct launcher.
//
// Playwright terminates the webServer process tree on shutdown (taskkill /T on
// Windows, SIGKILL on the process group on POSIX), so uvicorn is a child of
// this wrapper and dies with it - no orphaned :8000 server.
const { spawnSync, spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const BACKEND_DIR = path.join(ROOT, "apps", "backend");
const isCI = Boolean(process.env.CI);

// Where the bootstrap operator's MFA facts are stashed so the doctor-workspace
// E2E spec can drive a real operator login + decision (ticket #476). Under
// apps/backend/var/, which .gitignore marks as runtime-local storage.
const BOOTSTRAP_SEED_INFO = path.join(
  BACKEND_DIR,
  "var",
  "e2e-bootstrap-operator.json",
);
const BOOTSTRAP_OPERATOR_PHONE = "+919000000002";

function backendRun(moduleName, moduleArgs) {
  if (isCI) {
    return {
      command: "uv",
      args: ["run", "--directory", "apps/backend", moduleName, ...moduleArgs],
      cwd: ROOT,
    };
  }
  const venvName = process.env.CARESETU_BACKEND_ENV || "backend-env";
  const python = path.join(
    "D:\\Dev",
    "venvs",
    venvName,
    "Scripts",
    "python.exe",
  );
  return {
    command: python,
    args: ["-m", moduleName, ...moduleArgs],
    cwd: BACKEND_DIR,
  };
}

const migration = backendRun("alembic", [
  "-c",
  "alembic.ini",
  "upgrade",
  "head",
]);
const migrated = spawnSync(migration.command, migration.args, {
  cwd: migration.cwd,
  stdio: "inherit",
});
if (migrated.status !== 0) {
  process.exit(migrated.status === null ? 1 : migrated.status);
}

// Seed the idempotent demo identity + bootstrap operator (seed_demo.py) so the
// doctor-workspace E2E can activate a registered doctor through a real
// operator-scoped MFA login (ticket #476) - not by poking the tables. seed_demo
// is idempotent and converges on one operator row across repeated boots. The
// printed provisioning URI's TOTP secret is stashed in the runtime-local var
// dir for the spec to read; without it the operator leg of that spec cannot run.
const seed = backendRun("scripts.seed_demo", []);
const seeded = spawnSync(seed.command, seed.args, {
  cwd: seed.cwd,
  stdio: "pipe",
  encoding: "utf8",
});
if (seeded.status !== 0) {
  if (seeded.stderr) process.stderr.write(seeded.stderr);
  process.exit(seeded.status === null ? 1 : seeded.status);
}
const uriLine = (seeded.stdout || "")
  .split("\n")
  .find((line) => line.startsWith("bootstrap operator provisioning uri: "));
if (!uriLine) {
  process.stderr.write(
    "demo seed did not report a bootstrap operator provisioning uri\n",
  );
  process.exit(1);
}
const provisioningUri = uriLine
  .slice("bootstrap operator provisioning uri: ".length)
  .trim();
const totpSecret = new URL(provisioningUri).searchParams.get("secret");
if (!totpSecret) {
  process.stderr.write(
    "bootstrap operator provisioning uri carries no secret\n",
  );
  process.exit(1);
}
fs.mkdirSync(path.dirname(BOOTSTRAP_SEED_INFO), { recursive: true });
fs.writeFileSync(
  BOOTSTRAP_SEED_INFO,
  JSON.stringify(
    { phone: BOOTSTRAP_OPERATOR_PHONE, totp_secret: totpSecret },
    null,
    2,
  ),
);

const server = backendRun("uvicorn", ["app.main:app", "--port", "8000"]);
const uvicorn = spawn(server.command, server.args, {
  cwd: server.cwd,
  stdio: "inherit",
});
uvicorn.on("exit", (code) => process.exit(code ?? 1));
