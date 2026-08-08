# End-to-end tests — Playwright

Browser E2E against the running app (backend + frontend). Playwright's `webServer` in `playwright.config.ts` currently boots only the frontend dev server; the backend server process is wired in with the first feature E2E in `PHASE-1`.

- Feature E2Es land with their owning phase (roadmap §3.2 — e.g. mocked-SMS auth E2E in PHASE-2, full care-loop in PHASE-14).
- Browsers come from the shared global cache (`D:\Dev\tools\playwright-browsers`) — one download, all projects.
- Run with `npm run test:e2e` (headless) or `npm run test:e2e:ui` from the repo root.

Populated from `PHASE-2` onward.
