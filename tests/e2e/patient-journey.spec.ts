// PHASE-3 T11 (#220): patient-journey end-to-end spec.
//
// The whole phase proven as one patient journey in the browser, riding the
// live backend: open My Record, filter the timeline, walk the grant sheet to
// a visible receipt, revoke with the inline confirm, then observe the revoked
// receipts and the egress slice - with bilingual EN/HI toggle spot-checks
// along the way.
//
// Timeline entries are seeded by emitting synthetic outbox rows through the
// dispatcher in test setup (no producer exists yet by design). This is the
// phase's end-to-end gate on top of the auth-loop prior art.
//
// Runs alongside the auth-loop spec under the same `npm run test:e2e` command
// and shares the same playwright.config.ts boot pattern (live backend + mock
// SMS). Serial mode keeps this suite in one worker; each test gets its own
// browser context so sessions do not leak.

import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

test.describe.configure({ mode: "serial" });
test.setTimeout(120_000);

const BACKEND = "http://localhost:8000";

function randomPhone(): string {
  return `9${String(Math.floor(Math.random() * 1_000_000_000)).padStart(
    9,
    "0",
  )}`;
}

const phone = randomPhone();

async function startRegistration(page: Page, number: string): Promise<void> {
  await page.goto("/login");
  await expect(
    page.getByRole("heading", { name: "Verify & continue" }),
  ).toBeVisible({ timeout: 60_000 });
  await page.getByPlaceholder("10-digit mobile number").fill(number);
  await page.getByRole("button", { name: "Get verification code" }).click();
  const otpGroup = page.getByRole("group", { name: "OTP" });
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

async function getAuthInfo(
  request: APIRequestContext,
  page: Page,
): Promise<{ subjectId: string; jwt: string }> {
  const accessJwt = await page.evaluate(() =>
    localStorage.getItem("caresetu.access_jwt"),
  );
  expect(
    accessJwt,
    "JWT should exist in localStorage after login",
  ).toBeTruthy();
  const me = await request.get(`${BACKEND}/v1/me`, {
    headers: { Authorization: `Bearer ${accessJwt}` },
  });
  expect(me.status(), "GET /v1/me should succeed after login").toBe(200);
  const body = (await me.json()) as { subject_id: string };
  return { subjectId: body.subject_id, jwt: accessJwt! };
}

// ---- Seed helpers ----

async function seedRecordEntries(
  request: APIRequestContext,
  jwt: string,
): Promise<{ entry_ids: number[]; entry_types: string[] }> {
  const response = await request.post(`${BACKEND}/v1/test/seed`, {
    headers: { Authorization: `Bearer ${jwt}` },
  });
  expect(response.status(), "POST /v1/test/seed should succeed").toBe(200);
  return (await response.json()) as {
    entry_ids: number[];
    entry_types: string[];
  };
}

async function seedEgressData(
  request: APIRequestContext,
  jwt: string,
): Promise<{ egress_id: number }> {
  const response = await request.post(`${BACKEND}/v1/test/seed-egress`, {
    headers: { Authorization: `Bearer ${jwt}` },
  });
  expect(response.status(), "POST /v1/test/seed-egress should succeed").toBe(
    200,
  );
  return (await response.json()) as { egress_id: number };
}

// ---- Tests ----

test("patient journey: record -> filter -> grant sheet -> receipt -> revoke -> revoked receipts + egress slice", async ({
  page,
  request,
}) => {
  // 1. Register and authenticate
  await startRegistration(page, phone);
  await verifyOtp(page, request, phone);
  await page.waitForURL("**/patient");
  await expect(
    page.getByRole("heading", { name: "Welcome, Patient" }),
  ).toBeVisible();

  // Capture the subject ID and JWT for API seeding calls.
  const { subjectId, jwt } = await getAuthInfo(request, page);

  // 2. Seed record entries via synthetic outbox rows through the real dispatcher
  const seed = await seedRecordEntries(request, jwt);
  expect(
    seed.entry_ids.length,
    "seeding should create at least 2 entries",
  ).toBeGreaterThanOrEqual(2);
  expect(seed.entry_types).toContain("lab_report");
  expect(seed.entry_types).toContain("prescription");

  // 3. Navigate to My Record and verify timeline entries render
  await page.goto("/patient/record");
  await expect(page.getByTestId("record-timeline")).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByTestId(`entry-${seed.entry_ids[0]}`)).toBeVisible();

  // 4. Filter the timeline - click the prescriptions chip and verify filtering
  await page.getByTestId("filter-chip-prescription").click();
  await expect(page.getByTestId("filter-chip-prescription")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  // After filtering to prescriptions, only prescription entries should be visible
  const visibleEntries = page.locator('[data-testid^="entry-"]');
  await expect(visibleEntries).toHaveCount(1);
  // The visible entry should be the prescription (not the lab_report)
  const prescriptionEntryId =
    seed.entry_ids[seed.entry_types.indexOf("prescription")];
  await expect(page.getByTestId(`entry-${prescriptionEntryId}`)).toBeVisible();
  // Reset filter to see all entries again
  await page.getByTestId("filter-chip-all").click();
  await expect(page.getByTestId("filter-chip-all")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await expect(visibleEntries).toHaveCount(seed.entry_ids.length);

  // 5. Bilingual EN/HI spot-check on the record screen
  const langToggle = page.getByTestId("lang-toggle");
  await expect(langToggle).toBeVisible({ timeout: 5_000 });
  // Click the Hindi button to switch locale
  await langToggle.getByRole("button", { name: "हिं" }).click();
  // The record heading should switch to Hindi
  await expect(page.getByRole("heading", { name: "मेरा रिकॉर्ड" })).toBeVisible(
    { timeout: 5_000 },
  );
  // Toggle back to English
  await langToggle.getByRole("button", { name: "EN" }).click();
  await expect(
    page.getByRole("heading", { name: "My Record", exact: true }),
  ).toBeVisible({
    timeout: 5_000,
  });

  // 6. Open the grant sheet via the consent-demo-trigger on the patient page
  await page.goto("/patient");
  await expect(
    page.getByRole("heading", { name: "Welcome, Patient" }),
  ).toBeVisible();
  await page.getByTestId("consent-demo-trigger").click();
  await expect(page.getByTestId("consent-title")).toBeVisible();

  // 7. Grant consent through the UI and verify the receipt
  await page.getByTestId("consent-allow").click();
  // The receipt should appear after the grant API call succeeds
  await expect(page.getByTestId("consent-receipt-title")).toBeVisible({
    timeout: 10_000,
  });
  await expect(page.getByTestId("consent-receipt-line1")).toBeVisible();
  await expect(page.getByTestId("consent-receipt-line2")).toBeVisible();
  await expect(page.getByTestId("consent-receipt-line3")).toBeVisible();

  // Close the receipt sheet
  await page.keyboard.press("Escape");
  await page.waitForTimeout(500);

  // 9. Seed egress data so the egress slice renders on the consent log
  await seedEgressData(request, jwt);

  // 10. Navigate to consent log
  await page.goto("/patient/record/consent-log");
  await expect(page.getByTestId("history-section")).toBeVisible({
    timeout: 30_000,
  });

  // 11. Verify the granted consent appears in history
  const consentCards = page.locator('[data-testid^="consent-"]').filter({
    hasNot: page.locator('[data-testid="consent-log-loading"]'),
  });
  const grantedCard = consentCards.first();
  await expect(grantedCard).toBeVisible();

  // 12. Verify the egress slice renders
  await expect(page.getByTestId("egress-section")).toBeVisible();
  await expect(page.getByTestId("egress-table")).toBeVisible();

  // 13. Expand the receipt timeline on the granted consent
  const receiptDetails = page.locator('[data-testid^="receipt-"]').first();
  await expect(receiptDetails).toBeVisible();
  await receiptDetails.locator("summary").click();
  // The receipt should show at least "Granted" event
  await expect(receiptDetails.getByText(/Granted|granted/)).toBeVisible();

  // 14. Revoke the consent with the inline confirm
  const revokeBtn = page.locator('[data-testid^="revoke-"]').first();
  await expect(revokeBtn).toBeVisible();
  await revokeBtn.click();
  // The revoke confirmation sheet should open
  await expect(page.getByTestId("revoke-sheet")).toBeVisible();
  await expect(page.getByTestId("revoke-confirm")).toBeVisible();
  await page.getByTestId("revoke-confirm").click();
  // The toast should appear confirming revocation
  await expect(page.getByTestId("toast")).toBeVisible({ timeout: 10_000 });

  // 15. Verify the consent is now revoked in the history
  await expect(page.getByTestId("history-section")).toBeVisible();
  const revokedCard = page.locator('[data-testid^="consent-"]').filter({
    has: page.getByText("Revoked"),
  });
  await expect(revokedCard).toBeVisible();

  // 16. Verify the stop-forward copy appears on the revoked consent
  const stopForward = page.locator('[data-testid^="stop-forward-"]').first();
  await expect(stopForward).toBeVisible();

  // 17. Verify the egress slice is still visible post-revocation
  await expect(page.getByTestId("egress-section")).toBeVisible();
  await expect(page.getByTestId("egress-table")).toBeVisible();

  // 18. Bilingual spot-check on consent log screen
  await langToggle.getByRole("button", { name: "हिं" }).click();
  await expect(page.getByRole("heading", { name: "अनुमति लॉग" })).toBeVisible({
    timeout: 5_000,
  });
  await langToggle.getByRole("button", { name: "EN" }).click();
  await expect(page.getByRole("heading", { name: "Consent log" })).toBeVisible({
    timeout: 5_000,
  });
});
