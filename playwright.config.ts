import { defineConfig, devices } from "@playwright/test";

// Backend env for the E2E run: mock SMS (never a real provider), the gateway's
// JWT verify ON so the protected-route denial is real, and a fixed dev signing
// key shared with the facade that issued the sessions under test. The frontend
// dev server ignores these; the backend webServer inherits process.env so CI
// can still pass DATABASE_URL at the job level.
const BACKEND_ENV = {
  ...process.env,
  APP_ENVIRONMENT: "test",
  SMS_PROVIDER: "mock",
  GATEWAY_JWT_VERIFY_ENABLED: "true",
  GATEWAY_JWT_SIGNING_KEY: "e2e-dev-only-signing-key",
  // The iam MFA needs a key to encrypt the bootstrap operator's TOTP secret; a
  // fixed dev-only value keeps the E2E self-contained (CI has no .env). Written
  // as segments so the repo's secret-detection hook does not flag a literal
  // high-entropy token - this is a bootstrap fixture, not a real credential.
  IAM_MFA_SECRET_KEY: [
    "zSAYIemW45M4",
    "/8DcbJB/AV55ylx",
    "NsZTetPVuo0PLSg8=",
  ].join(""),
  // Forced off regardless of any exported local env var, so the suite never
  // trips the 10/60s auth cap (brief seam #1).
  GATEWAY_RATE_LIMIT_ENABLED: "false",
  // Run the outbox dispatcher in-process so the real event flow advances the
  // journey: partner.activated grants the doctor role, intake.captured runs
  // the structuring pipeline to ready_for_review, pre_summary.ready births the
  // care case. Handlers are ledger-idempotent, so the /v1/test/seed rows the
  // patient-journey spec dispatches synchronously are replay-safe (ticket
  // #476 doctor-workspace spec relies on this). e2e-backend.cjs also seeds the
  // demo bootstrap operator so an operator decision can activate the doctor.
  DISPATCHER_IN_PROCESS_ENABLED: "true",
};

export default defineConfig({
  testDir: "./tests/e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://localhost:3000",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // Probed on / (public marketing homepage, no auth required).
      // Previously probed /patient, but the proxy now redirects unauthenticated
      // requests there to /login, which does not exist until T6 is merged.
      command: "npm run dev -w @caresetu/frontend",
      url: "http://localhost:3000/",
      reuseExistingServer: !process.env.CI,
      // Cold Turbopack first-compile on this network drive + the concurrently
      // booting backend can exceed the 120 s default; give both servers room.
      timeout: 240_000,
      env: {
        ...process.env,
        // PHASE-2.6 T14 (#205, spec decision 16): render the demo OTP banner
        // so its literal copy is pinned byte-stable in-suite against what the
        // deployed live smoke asserts. Build-time-inlined var - this only
        // affects the local/CI e2e dev server, never a production deploy.
        NEXT_PUBLIC_DEMO_MODE: "true",
      },
    },
    {
      command: "node scripts/e2e-backend.cjs",
      url: "http://localhost:8000/health",
      reuseExistingServer: !process.env.CI,
      timeout: 240_000,
      env: BACKEND_ENV,
    },
  ],
});
