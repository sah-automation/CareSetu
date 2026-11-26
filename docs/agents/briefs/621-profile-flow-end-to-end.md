# Brief - #621 Prove the profile flow end to end in the doctor workspace

**Ticket:** #621 · **Parent:** #599 · **Refreshed:** 2026-09-30
**Reading surface:** ~7.8K tokens (budget 10K) - within budget

## Scope

The doctor profile has no end-to-end coverage. This extends the existing doctor-workspace spec, which already registers and activates a doctor and therefore already has everything needed: an active doctor lands on the profile page, completes the address, saves, and sees the public profile reflect it.

Acceptance criteria:

- [ ] An active doctor lands on the profile page and the page renders its sections.
- [ ] The doctor completes the structured address and saves, and the save succeeds.
- [ ] A PIN that cannot be resolved shows its error under the PIN input and the doctor can still save another section afterwards.
- [ ] The public profile then shows the address, clinic name and specialties the doctor just declared.
- [ ] The doctor's latitude and longitude inputs do not exist on the page.

## Read-list (in order)

1. `CONTEXT.md` build-session protocol, cross-reference rule and do-not-read gate - the doc map, and the rule that `docs/archive/` is never read (~0.6K tokens)
2. `docs/standards/coding-standards.md` section 6 (Tests) - the e2e row of the harness table (`Playwright`, `tests/e2e`, browsers shared from the global cache, `npm run test:e2e`) and the rule that a test asserts what a person sees, with the `FEAT-xxx` id in the test docstring (~0.4K)
3. The doctor-workspace Playwright spec, in full - the module header comment (why the journey needs a real active doctor, a real `ready_for_review` intake, and a real assignment), `test.describe.configure({ mode: "serial" })`, `test.setTimeout(180_000)`, the module-scope `doctorPhone` / `patientPhone` / captured `doctorPartnerId` / captured `intakeId` chain, and the helpers `randomPhone`, `readBootstrapSeedInfo`, `base32Decode`, `totpCode`, `readMockOtp`, `bearer`, `operatorLogin`, `registerPatient`, `startPartnerRegistration`, `confirmPartnerPhone`, `capturePartnerId`, `activeDoctorLogin`. The new test is the serial chain's next link, so this ordering contract is the whole prerequisite (~4.0K)
4. `playwright.config.ts` - the `BACKEND_ENV` block (mock SMS, gateway JWT verify on, the fixed dev signing key, the bootstrap MFA key, the forced-off rate limit, `DISPATCHER_IN_PROCESS_ENABLED`), the two `webServer` entries with their 240 s timeouts and `reuseExistingServer`, `testDir`, `fullyParallel`, and the single chromium project. This is what makes the run self-contained and what the new test inherits for free (~0.8K)
5. The route guard - `HINT_COOKIE` and `hintCookieString` in the session module, and `proxy` (`APP_GROUPS`, `matchesAppGroup`, `hasSessionCookie`, the `config.matcher` entry for `/doctor/:path*`, and `RETURN_PARAM`). A deep link into `/doctor/profile` without the hint cookie redirects to the staff login and carries the original path in the return param, which is the single most likely way the first assertion of this ticket fails silently (~1.0K)
6. The selector surface, located by symbol rather than by reading the page source: the `data-testid` inventory of the doctor profile page (`profile-skeleton`, `profile-save`, `profile-saved`, `profile-invalid`, `profile-latitude`, `profile-longitude`, `profile-address`, `profile-verified`, `profile-credentials`, `profile-public-preview`, `fee-editor`, and the rest) and of the public `ProviderProfile` component (`profile-hero`, `profile-name`, `profile-verified`, `profile-subtitle`, `profile-credentials`, `credential-row`, `profile-details`, `profile-loading`, `profile-not-found`, `profile-error`), plus the `fetchProviderProfile` response type in the directory profile client. Enough to choose stable locators after the redesign renames them (~1.0K)

## Do NOT read

- The doctor profile page source in full. It is being rewritten by #605 / #615 / #616 / #617 and a 39 KB `"use client"` file is a poor contract to write a test against; locate by `data-testid` and by accessible role/label instead.
- Unrelated modules and their pages; the patient profile pages; the patient journey and auth-loop e2e specs (named in the spec's "prior art" line, not needed to extend it).
- `docs/archive/`.
- Anything under `docs/roadmap` or `docs/architecture` beyond what the read-list names.
- The profile page's vitest suite and the shared profile context suites - those are #617's surface, not this ticket's.

## Baseline verify (must pass before the first edit)

- `npm run typecheck`
- `npm run test:e2e` - **needs the shared Playwright browser cache** under `D:\Dev\tools\`. If the browsers are missing, the run fails at launch rather than skipping; install them from the tooling README first, then re-run. This is slow (it boots a Next dev server and a real backend), so budget several minutes and expect the three existing serial tests to run first.

## Done-verify (acceptance criteria -> commands)

- `npm run test:e2e` - the new test runs in the same serial chain, so the whole spec (four tests) must be green, not just the new one. Serial mode means a failure in an earlier link skips the later ones: read the reporter output carefully and confirm the new test actually executed rather than being skipped by an earlier failure.
- `npm run typecheck`
- `npm run lint`

## Handoff notes

- **Blocker.** This ticket waits on **#619 (batch ordinal #20) Render the declared band on the public provider profile**, which lands the declared band on the public page plus the shared presentational renderer. The acceptance criterion "the public profile then shows the address, clinic name and specialties the doctor just declared" is a test of #619's output, so the e2e assertions must be written against the band that actually shipped, not against the plan. Read #619's brief and its closing comment before writing the locators.
- **Add the test as the last link in the existing serial chain, not as a new spec file.** The spec is `test.describe.configure({ mode: "serial" })` and shares one `doctorPhone`, one `patientPhone`, one `doctorPartnerId` and one `intakeId` at module scope across its tests. A new file would re-register and re-activate a second doctor and pay the full operator-activation cost again; a new test in the existing file reuses an already-active doctor and adds seconds. Each test gets its own browser context, so sessions do not leak between links - call `activeDoctorLogin` again rather than assuming a session survived.
- **Latency gates, not fixed sleeps.** The existing links use `expect.poll` with a 30 s timeout and 1.5 s intervals for anything that crosses the backend, and multi-second timeouts on first paint. Follow that. The address save, the PIN resolution and the public-profile re-read all cross the backend; a bare `waitForTimeout` will pass locally and flake in CI.
- **The unresolvable-PIN case needs a well-formed but unlisted PIN.** Pick a syntactically valid 6-digit PIN that is absent from the bundled centroid dataset, so the failure is "not resolvable" and not "malformed". If the seed dataset turns out to cover every plausible test PIN, extend it deliberately rather than reaching for a malformed value, which would exercise a different branch.
- **"The other section still saves" is the criterion most likely to regress.** After the failed PIN save, drive a _different_ section's save button and assert its own saved confirmation appears. This is the end-to-end counterpart of the #605 per-section edit-buffer rule, and it is the assertion that would catch a page-level buffer collapsing back into one.
- **"Latitude and longitude inputs do not exist" is a negative assertion.** Use `expect(locator).toHaveCount(0)` on the specific locators, not a bare absence check on a container, so the assertion cannot pass because the page failed to render. Note that the redesign removes those testids; if they are gone, assert on the accessible labels (`Latitude`, `Longitude`) having count 0, which survives the rename.
- **The route guard is the most likely silent failure.** `proxy` matches `/doctor/:path*` and bounces any hit without a non-empty `caresetu_authed` hint cookie to the staff login, preserving the original path in the return param. A `page.goto("/doctor/profile")` that happens before `activeDoctorLogin` completes will land on the login page and every later locator will fail for the wrong reason. Log in first, then navigate.
- **Test-id collision to watch.** `profile-verified` and `profile-credentials` are emitted by both the doctor page and the public `ProviderProfile` component. The new test moves between the two surfaces, so scope every locator to the page it belongs to, or prefer a section-scoped container. After the redesign both surfaces render through one shared component, so the collision may become intentional - but the assertion must still say which surface it is reading.
- **Relevant ADRs.**
  - **ADR-0005 (cookie/localStorage dual JWT, as amended)** - the secret-free presence-hint cookie the route guard reads. The guard checks presence only and never decodes claims; real authorization stays at the API gateway.
  - **ADR-0007 (split-origin deployment and session invariants)** - read before touching anything session-shaped on this page. The e2e run is same-origin localhost, which is exactly the condition where a split-origin bug passes locally.
  - **ADR-0016 (partner login method - phone OTP)** - why the active doctor logs in through the staff OTP form and lands on `/doctor`, which is the entry point the new test must leave before navigating to the profile.
  - **ADR-0019 (derived doctor patients list)** - the precedent for a doctor-console e2e extension riding the operator-activation seam rather than seeding state by hand.
- **Judgement call while mapping the surface.** The ticket body lists "the profile page and the public provider profile route as they now stand" on the read-list. The profile page today is a single 39 KB `"use client"` file that #605/#615/#616/#617 are splitting, so reading it whole would cost more than the entire budget and would be stale by the time the test runs. Item 6 reads the `data-testid` inventory and the public response type instead - the same facts the test needs, at a twelfth of the cost.
