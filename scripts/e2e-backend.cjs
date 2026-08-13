// Boots the CareSetu backend for the Playwright E2E suite: applies the schema
// migration, then serves the API on :8000. Playwright's webServer entry runs
// this command; the config's `env` sets APP_ENVIRONMENT=test, SMS_PROVIDER=mock
// and enables the gateway JWT verify so the protected-route denial is real.
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
const path = require("node:path");

const ROOT = path.resolve(__dirname, "..");
const BACKEND_DIR = path.join(ROOT, "apps", "backend");
const isCI = Boolean(process.env.CI);

function backendRun(moduleName, moduleArgs) {
  if (isCI) {
    return {
      command: "uv",
      args: ["run", "--directory", "apps/backend", moduleName, ...moduleArgs],
      cwd: ROOT,
    };
  }
  const venvName = process.env.CARESETU_BACKEND_ENV || "backend-env";
  const python = path.join("D:\\Dev", "venvs", venvName, "Scripts", "python.exe");
  return {
    command: python,
    args: ["-m", moduleName, ...moduleArgs],
    cwd: BACKEND_DIR,
  };
}

const migration = backendRun("alembic", ["-c", "alembic.ini", "upgrade", "head"]);
const migrated = spawnSync(migration.command, migration.args, {
  cwd: migration.cwd,
  stdio: "inherit",
});
if (migrated.status !== 0) {
  process.exit(migrated.status === null ? 1 : migrated.status);
}

const server = backendRun("uvicorn", ["app.main:app", "--port", "8000"]);
const uvicorn = spawn(server.command, server.args, {
  cwd: server.cwd,
  stdio: "inherit",
});
uvicorn.on("exit", (code) => process.exit(code ?? 1));
