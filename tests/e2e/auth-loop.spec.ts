import AxeBuilder from "@axe-core/playwright";
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

// The Phase 2 release loop driven end to end in the browser: register -> OTP
// (mocked SMS) -> verify -> authenticated session -> access a protected route.
// Runs against the live backend booted by playwright.config.ts with the mock
// SMS adapter, the gateway's JWT verify enabled, and the dev/test-only
// mock-OTP read-back route (see apps/backend/app/main.py).
//
// PHASE-2.6 T07 (#198) extends the loop with the cookie-presence route guard:
// a signed-out hit on a patient app route must land on the group-correct
// entry (/login) carrying ?return=<original>, staff groups must target
// /staff/login, and completing sign-in must land back on the original
// destination - proven end-to-end by a query marker that only survives if the
// return-url drove the post-auth navigation.
//
// PHASE-2.6 T14 (#205, spec #191 decisions 15/16) completes the guard story
// for the resolved route structure: the staff entry now renders (ticket 10),
// axe extends to the homepage and the open consent sheet, and a dedicated
// stability test pins the deployed-smoke literals (the /login path and the
// demo OTP banner copy) byte-stable in-suite. A staff POST-login landing is
// not drivable end to end this phase - no staff session can be minted (staff
// auth is Phase 5; registration grants only the patient role), so the staff
// landing matrix stays covered at unit level (staff-routing.test.ts).
//
// The first three tests share one randomly-chosen phone so the duplicate
// re-register case resolves against the SAME identity the first test
// registered. Serial mode keeps them in one worker in order; each test gets
// its own browser context, so the sessions do not leak between tests.

test.describe.configure({ mode: "serial" });

// The first-ever compile of /patient under a fresh Next dev server is far
// slower than the 30s default action timeout on cold filesystems (this repo
// sits on a network drive - Next logs "Slow filesystem detected"). Inflate the
// whole suite so cold-start compiles resolve before any interaction times out.
test.setTimeout(120_000);

const FRONTEND = "http://localhost:3000";
const BACKEND = "http://localhost:8000";

function randomPhone(): string {
  return `9${String(Math.floor(Math.random() * 1_000_000_000)).padStart(
    9,
    "0",
  )}`;
}

const phone = randomPhone();

// Captured by the first test from /v1/me and asserted by the second: proves
// the duplicate re-registration resolves to the SAME identity, not a new one.
let registeredSubjectId: string | null = null;

async function startRegistration(page: Page, number: string): Promise<void> {
  await page.goto("/login");
  // The wizard renders null until hydration completes; wait for the phone step
  // to actually be on screen before touching the input so a slow first compile
  // cannot land us mid-hydration. Assertions do NOT inherit test.setTimeout -
  // they default to 5s, which a cold first compile can exceed.
  await expect(
    page.getByRole("heading", { name: "Verify & continue" }),
  ).toBeVisible({
    timeout: 60_000,
  });
  await page.getByPlaceholder("10-digit mobile number").fill(number);
  await page.getByRole("button", { name: "Get verification code" }).click();
  const otpGroup = page.getByRole("group", { name: "OTP" });
  // Re-registering a phone inside its 60 s resend cooldown is refused on the
  // phone step (register honours the resend cooldown - PHASE-2 REM T3): the
  // PWA shows the countdown instead of a fresh code. Wait the window out and
  // retry so the duplicate-login case still resolves to the same identity.
  await otpGroup
    .waitFor({ state: "visible", timeout: 15_000 })
    .catch(async () => {
      await expect(page.getByText("Resend in")).toBeVisible({
        timeout: 15_000,
      });
      await page.waitForTimeout(62_000);
      await page.getByRole("button", { name: "Get verification code" }).click();
      await expect(otpGroup).toBeVisible({ timeout: 30_000 });
    });
}

async function readMockOtp(
  request: APIRequestContext,
  number: string,
): Promise<string> {
  const url = `${BACKEND}/v1/auth/dev/otp?${new URLSearchParams({
    phone: `+91${number}`,
  })}`;
  const response = await request.get(url);
  expect(response.status(), "dev mock-OTP read-back should answer 200").toBe(
    200,
  );
  const body = (await response.json()) as { code: string | null };
  expect(
    body.code,
    `mock SMS should have sent a code to +91${number}`,
  ).not.toBeNull();
  return body.code as string;
}

async function verifyOtp(
  page: Page,
  request: APIRequestContext,
  number: string,
): Promise<void> {
  const code = await readMockOtp(request, number);
  await page.getByLabel("Verification code").fill(code);
  await page.getByRole("button", { name: "Verify & continue" }).click();
  await page.waitForURL("**/patient", { timeout: 15_000 });
}

// TEST-C2 (#131): accessibility regression guard. Axe scans run against the
// already-booted local stack once each stage is on screen, so the assertion is
// deterministic. The failure message lists the violating rule IDs (with impact
// and help text) instead of dumping the whole nodes array.
async function expectNoAxeViolations(page: Page, label: string): Promise<void> {
  const results = await new AxeBuilder({ page }).analyze();
  const failures = results.violations.map(
    (v) => `${v.id} (${v.impact}): ${v.help}`,
  );
  expect(
    failures,
    `${label} should report zero accessibility violations`,
  ).toEqual([]);
}

test("register a new number, read the mock OTP, verify, and reach the protected surface", async ({
  page,
  request,
}) => {
  await startRegistration(page, phone);
  await verifyOtp(page, request, phone);
  await page.waitForURL("**/patient");
  await expect(
    page.getByRole("heading", { name: "Welcome, Patient" }),
  ).toBeVisible();

  const accessJwt = await page.evaluate(() =>
    localStorage.getItem("caresetu.access_jwt"),
  );
  expect(
    accessJwt,
    "the wizard should store the access JWT in localStorage",
  ).not.toBeNull();

  const me = await request.get(`${BACKEND}/v1/me`, {
    headers: { Authorization: `Bearer ${accessJwt}` },
  });
  expect(me.status()).toBe(200);
  const meBody = (await me.json()) as { subject_id: string };
  expect(meBody.subject_id).toBeTruthy();
  registeredSubjectId = meBody.subject_id;

  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Welcome, Patient" }),
  ).toBeVisible();
});

test("re-registering the same number resolves to the existing identity and logs in", async ({
  page,
  request,
}) => {
  await startRegistration(page, phone);
  await expect(
    page.getByText(
      "This number is already registered - verifying logs you in.",
    ),
  ).toBeVisible();
  await verifyOtp(page, request, phone);
  await page.waitForURL("**/patient");
  await expect(
    page.getByRole("heading", { name: "Welcome, Patient" }),
  ).toBeVisible();

  const accessJwt = await page.evaluate(() =>
    localStorage.getItem("caresetu.access_jwt"),
  );
  expect(accessJwt, "re-login should store a fresh access JWT").not.toBeNull();
  const me = await request.get(`${BACKEND}/v1/me`, {
    headers: { Authorization: `Bearer ${accessJwt}` },
  });
  expect(me.status()).toBe(200);
  const meBody = (await me.json()) as { subject_id: string };
  expect(
    meBody.subject_id,
    "re-registering the same number must resolve to the same identity, never a duplicate",
  ).toBe(registeredSubjectId);
});

test("an unauthenticated attempt at the protected surface is denied", async ({
  page,
  request,
}) => {
  const me = await request.get(`${BACKEND}/v1/me`);
  expect(me.status()).toBe(401);

  // Cookie-presence proxy (PHASE-2.6 T07 #198), staff group: a signed-out
  // hit on /operator redirects to the staff entry point with the return-url
  // preserved. Since ticket 10 (#201) the entry surface exists, so the
  // redirect must land on a RENDERED sign-in (PHASE-2.6 T14 #205) - the
  // stale pre-T10 expectation of a post-redirect 404 would now fail. The
  // return param is consumed only at post-login, which stays unit-level this
  // phase (see the file header).
  const staffResponse = await page.goto("/operator");
  expect(page.url()).toBe(`${FRONTEND}/staff/login?return=%2Foperator`);
  expect(staffResponse?.status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible({
    timeout: 60_000,
  });

  // Patient group: a signed-out deep link lands on /login with the original
  // path+query preserved as ?return=... The src marker distinguishes the
  // honored return target from the wizard's default /patient landing.
  await page.goto("/patient?src=deep-link");
  expect(page.url()).toBe(
    `${FRONTEND}/login?return=${encodeURIComponent("/patient?src=deep-link")}`,
  );
  await expect(page.getByPlaceholder("10-digit mobile number")).toBeVisible({
    timeout: 60_000,
  });
  await expect(
    page.getByRole("heading", { name: "You're signed in" }),
  ).toHaveCount(0);

  // Post-auth return completes: sign in through the wizard and land back on
  // the exact deep-linked destination.
  const returnPhone = randomPhone();
  await page.getByPlaceholder("10-digit mobile number").fill(returnPhone);
  await page.getByRole("button", { name: "Get verification code" }).click();
  await expect(page.getByRole("group", { name: "OTP" })).toBeVisible({
    timeout: 30_000,
  });
  const code = await readMockOtp(request, returnPhone);
  await page.getByLabel("Verification code").fill(code);
  await page.getByRole("button", { name: "Verify & continue" }).click();
  await page.waitForURL(
    (url) =>
      url.pathname === "/patient" &&
      url.searchParams.get("src") === "deep-link",
    { timeout: 60_000 },
  );
  await expect(
    page.getByRole("heading", { name: "Welcome, Patient" }),
  ).toBeVisible();
});

test("the homepage, consent sheet, auth wizard and patient page pass the axe accessibility scan", async ({
  page,
  request,
}) => {
  // TEST-C2 (#131) + PHASE-2.6 T14 (#205, spec #191 decision 15): assert zero
  // axe violations on the resolved homepage, each wizard stage, the open
  // consent sheet, and the signed-in surface.
  await page.goto("/");
  await expect(
    page.getByRole("heading", {
      name: "Find trusted doctors, labs and chemists near you",
    }),
  ).toBeVisible({ timeout: 60_000 });
  await expectNoAxeViolations(page, "public homepage");

  const axePhone = randomPhone();

  await page.goto("/login");
  await expect(
    page.getByRole("heading", { name: "Verify & continue" }),
  ).toBeVisible({
    timeout: 60_000,
  });
  await expectNoAxeViolations(page, "auth wizard phone step");

  await startRegistration(page, axePhone);
  await expectNoAxeViolations(page, "auth wizard OTP step");

  await verifyOtp(page, request, axePhone);

  await expect(
    page.getByRole("heading", { name: "Welcome, Patient" }),
  ).toBeVisible();
  await expectNoAxeViolations(page, "signed-in patient page");

  // The consent sheet (T12 #203) scans while OPEN - the Radix overlay traps
  // focus and aria-hides the page behind it, so this is the state a
  // screen-reader user actually experiences at a consent moment.
  await page.getByTestId("consent-demo-trigger").click();
  await expect(page.getByTestId("consent-title")).toBeVisible();
  await expectNoAxeViolations(page, "open consent sheet");
  await page.keyboard.press("Escape");

  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Welcome, Patient" }),
  ).toBeVisible();
  await expectNoAxeViolations(page, "signed-in patient page after reload");
});

test("deployed-smoke stability: login route path and demo OTP banner copy are byte-stable", async ({
  page,
}) => {
  // PHASE-2.6 T14 (#205, spec #191 decision 16): the deployed live smoke
  // (scripts/live_smoke.py step 5) fetches /patient and /login and asserts
  // the literal "Demo OTP:" string in their served JS chunks. Any drift in
  // the login route path or the banner copy would surface only as a
  // post-deploy smoke failure - so both literals are pinned here, in-suite,
  // where they fail loudly before anything ships. The banner renders because
  // playwright.config.ts sets NEXT_PUBLIC_DEMO_MODE for the e2e dev server;
  // production deploys keep their own value.
  const stabilityPhone = randomPhone();

  await page.goto("/login");
  await expect(page).toHaveURL(`${FRONTEND}/login`);
  await startRegistration(page, stabilityPhone);
  await expect(page.getByText(/^Demo OTP: \d{6}$/)).toBeVisible({
    timeout: 15_000,
  });
});
