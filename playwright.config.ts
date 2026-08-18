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
  // Forced off regardless of any exported local env var, so the suite never
  // trips the 10/60s auth cap (brief seam #1).
  GATEWAY_RATE_LIMIT_ENABLED: "false",
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
      timeout: 120_000,
    },
    {
      command: "node scripts/e2e-backend.cjs",
      url: "http://localhost:8000/health",
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: BACKEND_ENV,
    },
  ],
});
