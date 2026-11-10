// Operator settings: toggle redis.enabled off in the Cache & Redis section, verify
// the save survives a reload and lands in the setting history (#898).

import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";

import {
  BACKEND_BASE_URL,
  BOOTSTRAP_OPERATOR_PHONE,
  readBootstrapSeedInfo,
  readMockOtp,
  totpCode,
} from "./helpers";

test.describe.configure({ mode: "serial" });
test.setTimeout(360_000);

async function activateOperatorIdentity(
  request: APIRequestContext,
): Promise<void> {
  const phone = BOOTSTRAP_OPERATOR_PHONE;

  for (let attempt = 0; attempt < 3; attempt++) {
    const session = await request.post(`${BACKEND_BASE_URL}/v1/auth/session`, {
      data: { phone },
    });
    if (session.status() === 200) {
      return;
    }

    const register = await request.post(
      `${BACKEND_BASE_URL}/v1/auth/register`,
      {
        data: { phone },
      },
    );
    expect(register.status(), "operator phone register should answer 200").toBe(
      200,
    );
    const otp = await readMockOtp(request, phone);
    if (otp !== null) {
      await request.post(`${BACKEND_BASE_URL}/v1/auth/verify`, {
        data: { phone, otp },
      });
    }

    const afterVerify = await request.post(
      `${BACKEND_BASE_URL}/v1/auth/session`,
      { data: { phone } },
    );
    if (afterVerify.status() === 200) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 20_000));
  }

  throw new Error(
    "operator identity never became Active (OTP verified) so it cannot sign in",
  );
}

async function waitForFormHydration(page: Page): Promise<void> {
  const phone = page.getByTestId("staff-phone");
  const phoneError = page.getByTestId("staff-phone-error");
  for (let attempt = 0; attempt < 60; attempt++) {
    await phone.fill("9");
    await phone.blur();
    if (await phoneError.isVisible()) {
      return;
    }
    await page.waitForTimeout(250);
  }
  throw new Error("the staff login form never hydrated");
}

async function signInAsOperator(
  page: Page,
  request: APIRequestContext,
): Promise<void> {
  const seed = readBootstrapSeedInfo();
  await activateOperatorIdentity(request);

  await page.goto("/staff/login?role=operator");
  await expect(page.getByTestId("staff-login-form")).toBeVisible({
    timeout: 60_000,
  });
  await waitForFormHydration(page);

  const phoneField = page.getByTestId("staff-phone");
  const totpField = page.getByTestId("staff-totp");

  let refusal = "no error notice";
  for (const windowOffset of [0, 1, -1]) {
    await phoneField.fill("9000000002");
    await totpField.fill(totpCode(seed.totp_secret, windowOffset));
    await page.getByTestId("staff-submit").click();

    const refused = await page
      .getByTestId("staff-login-error")
      .waitFor({ state: "visible", timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    if (refused) {
      refusal =
        (await page
          .getByTestId("staff-login-error")
          .textContent()
          .catch(() => "refused")) ?? "refused";
      continue;
    }

    try {
      await page.waitForURL(/\/operator(\?|$)/, { timeout: 60_000 });
      return;
    } catch {
      refusal = "login did not land";
    }
  }
  throw new Error(`operator sign-in failed for every TOTP window: ${refusal}`);
}

async function expandSection(page: Page, testId: string): Promise<void> {
  const toggle = page.getByTestId(`${testId}-toggle`);
  await expect(toggle).toBeVisible({ timeout: 60_000 });
  if ((await toggle.getAttribute("aria-expanded")) !== "true") {
    await toggle.click();
  }
  await expect(toggle).toHaveAttribute("aria-expanded", "true");
}

test("operator toggles redis.enabled off and verifies history + persistence", async ({
  page,
  request,
}) => {
  await signInAsOperator(page, request);

  await page.goto("/operator/settings");
  await expect(page.getByTestId("settings-shell")).toBeVisible({
    timeout: 60_000,
  });

  await expandSection(page, "settings-cache");
  await expect(
    page.getByTestId("settings-cache-row-redis.enabled"),
  ).toBeVisible({ timeout: 60_000 });

  const input = page.getByTestId("settings-cache-input-redis.enabled");
  const save = page.getByTestId("settings-cache-save-redis.enabled");

  await input.uncheck();
  await save.click();

  await expect(
    page.getByTestId("settings-cache-save-status-redis.enabled"),
  ).toHaveText(/Saved/i, { timeout: 30_000 });

  await page.reload();
  await expect(page.getByTestId("settings-shell")).toBeVisible({
    timeout: 60_000,
  });
  await expandSection(page, "settings-cache");
  await expect(input).not.toBeChecked({ timeout: 60_000 });

  // History shows a row for redis.enabled with a new false value.
  const historyRow = page
    .locator('[data-testid^="settings-cache-history-row-redis.enabled-"]')
    .first();
  await expect(historyRow).toBeVisible({ timeout: 60_000 });
  await expect(historyRow).toContainText(/No/i);
  // The history row carries the new value plus a timestamp (and an actor).
  await expect(historyRow).toContainText(/\d{4}/);
});
