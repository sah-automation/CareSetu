// PHASE-3 T11 (#220): patient-journey end-to-end spec.
//
// The whole phase proven as one patient journey in the browser, riding the
// live backend: open My Record, filter the timeline, seed a standing consent
// through the real consent API, revoke with the inline confirm, then observe
// the revoked receipts and the egress slice - with bilingual EN/HI toggle
// spot-checks along the way.
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

// #496: on every hard navigation into a patient-shell page, AuthContext's
// validate() re-resolves identity asynchronously, changing the ProfileProvider
// key ("anon" → identity) and remounting the patient subtree. Interacting
// before that remount completes races against the unmount (visible as
// "element is not stable" then "detached from the DOM" on any open sheet).
// Guard every hard goto that precedes stateful UI with a wait for the account
// menu's resolved identity - the earliest visual signal that identity settled.
// #521: the patient trigger is now an avatar with no visible digits, so the
// signal is the trigger's data-session-resolved flag (set only once /v1/me
// resolves) instead of trigger text - and it carries no phone data.
async function waitForIdentityResolved(page: Page): Promise<void> {
  await expect(page.getByTestId("account-menu")).toHaveAttribute(
    "data-session-resolved",
    "true",
    { timeout: 15_000 },
  );
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

// #499: the patient home no longer hosts the consent demo (the PROTO-2.7 shell
// demotes demo scaffolding), so a standing consent is seeded through the real
// consent API. The consent-log journey below still exercises the receipts,
// revoke and egress it always did; the interactive grant sheet is unit-covered
// (ConsentSheet.test.tsx) and returns to e2e via the real home consent moment
// when it lands.
async function seedConsentGrant(
  request: APIRequestContext,
  jwt: string,
): Promise<void> {
  const response = await request.post(`${BACKEND}/v1/consents`, {
    headers: { Authorization: `Bearer ${jwt}` },
    data: {
      counterparty_type: "lab",
      counterparty_id: "e2e-journey-consent",
      record_scope: "prescriptions",
    },
  });
  expect(response.status(), "POST /v1/consents should succeed").toBe(201);
}

// ---- Tests ----

test("patient journey: record -> filter -> seed consent -> revoke -> revoked receipts + egress slice", async ({
  page,
  request,
}) => {
  // The phone is scoped to the test body so a CI retry re-runs the whole
  // journey on a fresh identity, never re-seeding an already-populated record.
  const phone = randomPhone();

  // 1. Register and authenticate
  await startRegistration(page, phone);
  await verifyOtp(page, request, phone);
  await page.waitForURL("**/patient");
  await expect(page.getByTestId("patient-home-greeting")).toBeVisible();

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
  await waitForIdentityResolved(page);
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
  // After filtering to prescriptions, only prescription entries should be
  // visible. Scope to the entry TILE li: the tile's read-more link also carries
  // a `entry-link-{id}` testid (#511), so a bare `entry-` prefix match would
  // double-count every entry.
  const visibleEntries = page.locator('li[data-testid^="entry-"]');
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
  await expect(
    page.getByRole("heading", { name: "मेरा हेल्थ रिकॉर्ड" }),
  ).toBeVisible({ timeout: 5_000 });
  // Toggle back to English
  await langToggle.getByRole("button", { name: "EN" }).click();
  await expect(
    page.getByRole("heading", { name: "My Health Record", exact: true }),
  ).toBeVisible({
    timeout: 5_000,
  });

  // 6. Seed a standing consent through the real consent API (#499: the home's
  //    demo grant sheet is gone).
  await seedConsentGrant(request, jwt);

  // 7. Seed egress data so the egress slice renders on the consent log
  await seedEgressData(request, jwt);

  // 8. Navigate to consent log
  await page.goto("/patient/record/consent-log");
  await expect(page.getByTestId("history-section")).toBeVisible({
    timeout: 30_000,
  });

  // 9. Verify the granted consent appears in history
  const consentCards = page.locator('[data-testid^="consent-"]').filter({
    hasNot: page.locator('[data-testid="consent-log-loading"]'),
  });
  const grantedCard = consentCards.first();
  await expect(grantedCard).toBeVisible();

  // 10. Verify the egress slice renders
  await expect(page.getByTestId("egress-section")).toBeVisible();
  await expect(page.getByTestId("egress-table")).toBeVisible();

  // 11. Expand the receipt timeline on the granted consent
  const receiptDetails = page.locator('[data-testid^="receipt-"]').first();
  await expect(receiptDetails).toBeVisible();
  await receiptDetails.locator("summary").click();
  // The receipt should show at least "Granted" event
  await expect(receiptDetails.getByText(/Granted|granted/)).toBeVisible();

  // 12. Revoke the consent with the inline confirm
  const revokeBtn = page.locator('[data-testid^="revoke-"]').first();
  await expect(revokeBtn).toBeVisible();
  await revokeBtn.click();
  // The revoke confirmation sheet should open
  await expect(page.getByTestId("revoke-sheet")).toBeVisible();
  await expect(page.getByTestId("revoke-confirm")).toBeVisible();
  await page.getByTestId("revoke-confirm").click();
  // The toast should appear confirming revocation
  await expect(page.getByTestId("toast")).toBeVisible({ timeout: 10_000 });

  // 13. Verify the consent is now revoked in the history
  await expect(page.getByTestId("history-section")).toBeVisible();
  const revokedCard = page.locator('[data-testid^="consent-"]').filter({
    has: page.getByText("Revoked"),
  });
  await expect(revokedCard).toBeVisible();

  // 14. Verify the stop-forward copy appears on the revoked consent
  const stopForward = page.locator('[data-testid^="stop-forward-"]').first();
  await expect(stopForward).toBeVisible();

  // 15. Verify the egress slice is still visible post-revocation
  await expect(page.getByTestId("egress-section")).toBeVisible();
  await expect(page.getByTestId("egress-table")).toBeVisible();

  // 16. Bilingual spot-check on consent log screen
  await langToggle.getByRole("button", { name: "हिं" }).click();
  await expect(page.getByRole("heading", { name: "अनुमति लॉग" })).toBeVisible({
    timeout: 5_000,
  });
  await langToggle.getByRole("button", { name: "EN" }).click();
  await expect(page.getByRole("heading", { name: "Consent log" })).toBeVisible({
    timeout: 5_000,
  });
});
