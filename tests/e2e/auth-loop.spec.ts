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
//
// FEAT-014 T11 (#471) extends the loop with the partner register-and-login
// leg, back-to-back with the patient loop in the same session: a doctor
// completes the registration wizard, confirms the phone with the on-screen
// demo code (the same read-back path as the patient wizard - no separate demo
// plumbing), is signed into the partner surface, and lands on the pending
// status screen (the state-correct landing for a not-yet-activated partner).
// A second test then proves the "returns" leg - the fresh browser context
// signs the same number back in on the staff card with phone + SMS code and
// lands by state again.

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

// FEAT-014 T11 (#471): the doctor number the partner leg registers and then
// logs back in with. Shared across the two partner tests so the return login
// resolves to the SAME partner identity the wizard just created.
const partnerPhone = randomPhone();

// Captured by the first test from /v1/me and asserted by the second: proves
// the duplicate re-registration resolves to the SAME identity, not a new one.
let registeredSubjectId: string | null = null;

// FEAT-014 T11 (#471): captured by the partner registration leg from /v1/me
// and asserted by the return leg, so "their own state-correct screen" really
// means the SAME partner identity - never a different account on the phone.
let registeredPartnerSubjectId: string | null = null;

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

// FEAT-014 T11 (#471): fetch the caller's identity with a Bearer JWT. Shared
// by both partner legs so the session the wizard / staff-card login minted is
// proven real AND resolves to the same underlying partner.
async function readMe(
  request: APIRequestContext,
  accessJwt: string,
): Promise<{ subject_id: string; roles: string[] }> {
  const me = await request.get(`${BACKEND}/v1/me`, {
    headers: { Authorization: `Bearer ${accessJwt}` },
  });
  expect(me.status()).toBe(200);
  return (await me.json()) as { subject_id: string; roles: string[] };
}

// FEAT-014 T11 (#471): partner registration leg. Runs the whole provider
// wizard (/staff/register) for a doctor - account basics, identity, three
// credential uploads, review & declarations - then submits the application.
// The wizard's phone-confirmation step (not part of the stepper) is handled
// by confirmPartnerPhone.
async function startPartnerRegistration(
  page: Page,
  number: string,
): Promise<void> {
  await page.goto("/staff/register?type=doctor");
  await expect(
    page.getByRole("heading", { name: "Account basics" }),
  ).toBeVisible({ timeout: 60_000 });

  await page.getByTestId("pr-fullname").fill("Dr. E2E Partner");
  await page.getByTestId("pr-email").fill(`partner.e2e.${number}@example.com`);
  await page.getByTestId("pr-password").fill("CareSetu!E2E2026");
  await page.getByTestId("pr-mobile").fill(number);
  await page.getByTestId("pr-next").click();

  await expect(
    page.getByRole("heading", { name: "Professional identity" }),
  ).toBeVisible({ timeout: 60_000 });
  await page.getByTestId("pr-degreename").fill("MBBS");
  await page.getByTestId("pr-council").selectOption("jharkhandSmc");
  await page.getByTestId("pr-city").fill("Daltonganj");
  await page.getByTestId("pr-languages").fill("Hindi, English");
  await page.getByTestId("pr-next").click();

  await expect(
    page.getByRole("heading", { name: "Credentials upload" }),
  ).toBeVisible({ timeout: 60_000 });
  const credentialFile = {
    name: "credential.jpg",
    mimeType: "image/jpeg",
    buffer: Buffer.from("e2e-credential"),
  };
  await page
    .getByTestId("slot-input-councilCert")
    .setInputFiles(credentialFile);
  await page.getByTestId("slot-input-degrees").setInputFiles(credentialFile);
  await page.getByTestId("slot-input-photoId").setInputFiles(credentialFile);
  await page.getByTestId("pr-next").click();

  await expect(
    page.getByRole("heading", { name: "Review & declarations" }),
  ).toBeVisible({ timeout: 60_000 });
  await page.getByTestId("decl-truth").check();
  await page.getByTestId("decl-consent").check();
  await page.getByTestId("decl-terms").check();
  await page.getByTestId("pr-submit").click();
}

// FEAT-014 T11 (#471): partner phone-confirmation step. The wizard has already
// requested the code for the submitted number, so the demo banner drives the
// entry exactly like the patient wizard - the byte-stable "Demo OTP: NNNNNN"
// literal, read-back via the same mock-SMS API. A verified code mints the
// partner session and lands on the pending status screen (state-driven
// landing for a not-yet-activated doctor).
async function confirmPartnerPhone(
  page: Page,
  request: APIRequestContext,
  number: string,
): Promise<void> {
  await expect(page.getByTestId("pr-step-5")).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/^Demo OTP: \d{6}$/)).toBeVisible({
    timeout: 30_000,
  });
  const code = await readMockOtp(request, number);
  await page.getByTestId("pr-confirm-otp").fill(code);
  await page.getByTestId("pr-confirm-submit").click();
  await page.waitForURL("**/partner/status/pending", { timeout: 60_000 });
  await expect(
    page.getByRole("heading", { name: "Your application is being verified" }),
  ).toBeVisible({ timeout: 60_000 });
}

// FEAT-014 T11 (#471): partner return-login leg ("returns"). The staff card
// (/staff/login, partner mode) signs back in with phone + SMS code and lands
// by state again. The fresh context must carry no leaked session: the wizard's
// stored JWT is gone, so the sign-in really is from scratch. A login inside
// the 60s resend cooldown of the registration code is refused with a countdown
// on the phone step - wait the window out and retry so the same partner still
// resolves (latest-wins challenge).
async function partnerLogin(
  page: Page,
  request: APIRequestContext,
  number: string,
): Promise<void> {
  await page.goto("/staff/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible({
    timeout: 60_000,
  });

  const staleJwt = await page.evaluate(() =>
    localStorage.getItem("caresetu.access_jwt"),
  );
  expect(
    staleJwt,
    "a fresh browser context must not carry the registration session",
  ).toBeNull();

  await page.getByTestId("partner-phone").fill(number);
  await page.getByTestId("staff-submit").click();
  await expect(page.getByText(/^Demo OTP: \d{6}$/))
    .toBeVisible({
      timeout: 15_000,
    })
    .catch(async () => {
      await expect(page.getByText("Resend in")).toBeVisible({
        timeout: 15_000,
      });
      await page.waitForTimeout(62_000);
      await page.getByTestId("staff-submit").click();
      await expect(page.getByText(/^Demo OTP: \d{6}$/)).toBeVisible({
        timeout: 30_000,
      });
    });

  const code = await readMockOtp(request, number);
  await page.getByTestId("partner-otp").fill(code);
  await page.getByTestId("staff-submit").click();
  await page.waitForURL("**/partner/status/pending", { timeout: 60_000 });
  await expect(
    page.getByRole("heading", { name: "Your application is being verified" }),
  ).toBeVisible({ timeout: 60_000 });
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
  await expect(page.getByTestId("patient-home-greeting")).toBeVisible();

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
  await expect(page.getByTestId("patient-home-greeting")).toBeVisible();
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
  await expect(page.getByTestId("patient-home-greeting")).toBeVisible();

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

test("a fresh login resolves identity in-flow so profile Finish works without a reload (#496)", async ({
  page,
  request,
}) => {
  // #496 Seam 2: this is the regression the ticket shipped to kill - a brand
  // new patient signs in through the OTP wizard and can complete the profile
  // on the very first click of Finish, with no reload anywhere in between.
  // The pre-fix behavior "worked" only because a full reload re-ran session
  // validation; this test proves the seam resolves identity in-flow instead.
  const freshPhone = randomPhone();

  await startRegistration(page, freshPhone);
  await verifyOtp(page, request, freshPhone);
  await page.waitForURL("**/patient");

  // No-reload invariant: exactly one full page navigation has ever happened
  // (the initial /login goto). The OTP redirect and the account menu must be
  // client-side.
  const navigations = await page.evaluate(
    () => performance.getEntriesByType("navigation").length,
  );
  expect(
    navigations,
    "the fresh-login chain must reach /patient with a single page navigation",
  ).toBe(1);

  // The seam resolved identity from the stored session: the dashboard renders
  // the avatar trigger flagged as resolved (the patient trigger no longer
  // shows the last two digits anywhere, #521). The flag carries no phone.
  await expect(page.getByTestId("account-menu")).toHaveAttribute(
    "data-session-resolved",
    "true",
  );

  // Reach the completion wizard directly. #499 removed the home's nudge stack
  // (PROTO-2.7 demotes profile completion to a slim banner, ticket #500), so
  // there is no in-page CTA to click here; the wizard itself is unchanged.
  // The hard goto re-resolves identity (see the identity-remount guard note),
  // so wait for the account menu to settle before touching the form.
  await page.goto("/patient/profile/complete");
  await expect(page.getByTestId("account-menu")).toHaveAttribute(
    "data-session-resolved",
    "true",
  );

  // Fill the required basics and Finish on the very first attempt.
  await page.getByTestId("pc-fullname").fill("E2E Asha");
  await page.getByTestId("pc-age").fill("30");
  await page.getByTestId("pc-gender").selectOption("female");
  await page.getByTestId("pc-next").click();
  await expect(
    page.getByTestId("profile-save-error"),
    "basics complete and identity resolved - Finish must not surface a save error",
  ).toHaveCount(0);
  await page.getByTestId("pc-skip").click();
  await page.getByTestId("pc-next").click();

  // The save succeeded: the wizard redirected home and the profile persisted.
  await page.waitForURL("**/patient");
  const accessJwt = await page.evaluate(() =>
    localStorage.getItem("caresetu.access_jwt"),
  );
  expect(accessJwt).not.toBeNull();
  const profile = await request.get(`${BACKEND}/v1/me/profile`, {
    headers: { Authorization: `Bearer ${accessJwt}` },
  });
  expect(profile.status()).toBe(200);
  const body = (await profile.json()) as {
    set: boolean;
    profile: { name: string };
  };
  expect(body.set, "the completed profile must persist on the server").toBe(
    true,
  );
  expect(body.profile.name).toBe("E2E Asha");
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
  expect(page.url()).toBe(
    `${FRONTEND}/staff/login?role=operator&return=%2Foperator`,
  );
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
  await expect(page.getByTestId("patient-home-greeting")).toBeVisible();
});

test("the homepage, consent overlay, auth wizard and patient page pass the axe accessibility scan", async ({
  page,
  request,
}) => {
  // TEST-C2 (#131) + PHASE-2.6 T14 (#205, spec #191 decision 15): assert zero
  // axe violations on the resolved homepage, each wizard stage, the open
  // consent overlay, and the signed-in surface.
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

  await expect(page.getByTestId("patient-home-greeting")).toBeVisible();
  await expectNoAxeViolations(page, "signed-in patient page");

  // The consent overlay scans while OPEN - the Radix sheet traps focus and
  // aria-hides the page behind it, so this is the state a screen-reader user
  // experiences at a consent moment. #499 removed the home's demo grant sheet,
  // so seed a standing consent through the real consent API and scan the open
  // revoke sheet on the consent log - the same focus-trapped overlay anatomy.
  const consentJwt = await page.evaluate(() =>
    localStorage.getItem("caresetu.access_jwt"),
  );
  expect(consentJwt).not.toBeNull();
  const grant = await request.post(`${BACKEND}/v1/consents`, {
    headers: { Authorization: `Bearer ${consentJwt}` },
    data: {
      counterparty_type: "lab",
      counterparty_id: "e2e-axe-consent",
      record_scope: "prescriptions",
    },
  });
  expect(grant.status()).toBe(201);

  await page.goto("/patient/record/consent-log");
  // #496 hard-goto guard (same as patient-journey's waitForIdentityResolved):
  // the patient subtree remounts asynchronously once AuthContext re-resolves
  // identity, and touching the revoke targets before that remount finishes
  // races against the unmount. Wait for the trigger's data-session-resolved
  // flag before interacting.
  await expect(page.getByTestId("account-menu")).toHaveAttribute(
    "data-session-resolved",
    "true",
  );
  await expect(page.getByTestId("history-section")).toBeVisible({
    timeout: 30_000,
  });
  await page.locator('[data-testid^="revoke-"]').first().click();
  await expect(page.getByTestId("revoke-sheet")).toBeVisible();
  await expectNoAxeViolations(page, "open revoke sheet");
  await page.keyboard.press("Escape");

  // The consent moment leaves us on the consent log, which has no greeting
  // strip; the pre-#499 reload here landed on the home's consent sheet. Return
  // to the signed-in home first, then reload, so the session-persistence check
  // still means "the patient surface renders after a full reload".
  await page.goto("/patient");
  await expect(page.getByTestId("account-menu")).toHaveAttribute(
    "data-session-resolved",
    "true",
  );
  await page.reload();
  await expect(page.getByTestId("patient-home-greeting")).toBeVisible();
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

test("partner: register a doctor through the wizard, confirm the phone with the demo code, and land on the pending status screen", async ({
  page,
  request,
}) => {
  // FEAT-014 T11 (#471) leg 1: a fresh doctor number completes the provider
  // wizard, confirms the phone with the demo read-back (identical code-entry
  // path to the patient wizard), and is signed into the partner surface on
  // the state-correct self-service screen - the pending status page.
  await startPartnerRegistration(page, partnerPhone);
  await confirmPartnerPhone(page, request, partnerPhone);
  await expect(page).toHaveURL(`${FRONTEND}/partner/status/pending`);

  const accessJwt = await page.evaluate(() =>
    localStorage.getItem("caresetu.access_jwt"),
  );
  expect(
    accessJwt,
    "the register-and-confirm flow should store a partner access JWT",
  ).not.toBeNull();
  const me = await readMe(request, accessJwt as string);
  expect(
    me.roles,
    "the wizard session must carry the partner role, never just patient",
  ).toContain("partner");
  registeredPartnerSubjectId = me.subject_id;
});

test("partner: close and reopen the browser, sign back in with phone + code, and land by state again", async ({
  page,
  request,
}) => {
  // FEAT-014 T11 (#471) leg 2 ("returns"): this test's fresh browser context
  // holds no session (partnerLogin proves the slate is clean), so the
  // returning partner sign in from scratch on the staff card with phone +
  // SMS code and lands on the same state-correct pending screen.
  await partnerLogin(page, request, partnerPhone);
  await expect(page).toHaveURL(`${FRONTEND}/partner/status/pending`);

  const returnJwt = await page.evaluate(() =>
    localStorage.getItem("caresetu.access_jwt"),
  );
  expect(
    returnJwt,
    "the return login should mint a fresh partner session",
  ).not.toBeNull();
  const me = await readMe(request, returnJwt as string);
  expect(
    me.subject_id,
    "the returning partner must resolve to the SAME identity the wizard created, never a new account",
  ).toBe(registeredPartnerSubjectId);
});
