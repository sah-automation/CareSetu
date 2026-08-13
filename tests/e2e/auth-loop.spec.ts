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
// The three tests share one randomly-chosen phone so the duplicate re-register
// case resolves against the SAME identity the first test registered. Serial
// mode keeps them in one worker in order; each test gets its own browser
// context, so the sessions do not leak between tests.

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
  await page.goto("/patient");
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
  await expect(page.getByRole("group", { name: "OTP" })).toBeVisible();
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
  await expect(
    page.getByRole("heading", { name: "Identity verified" }),
  ).toBeVisible();
}

test("register a new number, read the mock OTP, verify, and reach the protected surface", async ({
  page,
  request,
}) => {
  await startRegistration(page, phone);
  await verifyOtp(page, request, phone);
  await page.getByRole("button", { name: "Go to CareSetu home" }).click();
  await expect(
    page.getByRole("heading", { name: "You're signed in" }),
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
    page.getByRole("heading", { name: "You're signed in" }),
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
  await page.getByRole("button", { name: "Go to CareSetu home" }).click();
  await expect(
    page.getByRole("heading", { name: "You're signed in" }),
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

  await page.goto("/patient");
  await expect(page.getByPlaceholder("10-digit mobile number")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "You're signed in" }),
  ).toHaveCount(0);
});
