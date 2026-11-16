// Operator settings: admin walks the AI & LLM section - switches provider,
// picks a chat model, saves a price, and observes effective values update
// (#926). Modeled on operator-settings-cache-redis.spec.ts.

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

const PROVIDER_MOCK = "mock";
const PROVIDER_OPENAI = "openai_compatible";
const MODEL_OPENAI = "openai/gpt-oss-120b";

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
      { data: { phone } },
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

test("admin switches provider and model, saves, and sees effective values update", async ({
  page,
  request,
}) => {
  await signInAsOperator(page, request);

  await page.goto("/operator/settings");
  await expect(page.getByTestId("settings-shell")).toBeVisible({
    timeout: 60_000,
  });

  await expandSection(page, "settings-ai");

  const providerSelect = page.getByTestId("settings-ai-provider-select");
  await expect(providerSelect).toBeVisible({ timeout: 60_000 });

  // Dependent filtering: switching provider re-filters the chat model options.
  await providerSelect.selectOption(PROVIDER_OPENAI);

  const modelSelect = page.getByTestId("settings-ai-model-select");
  // Pick a model from the newly available catalog while the provider draft is
  // still set, so the model's catalog validation passes on save.
  await modelSelect
    .locator(`option[value="${MODEL_OPENAI}"]`)
    .waitFor({ state: "attached", timeout: 30_000 });
  await modelSelect.selectOption(MODEL_OPENAI);
  await expect(modelSelect).toHaveValue(MODEL_OPENAI);

  const modelSave = page.getByTestId(`settings-ai-save-ai.model`);
  await modelSave.click();
  await expect(page.getByTestId("settings-ai-save-status-ai.model")).toHaveText(
    /Saved/i,
    { timeout: 30_000 },
  );

  const providerSave = page.getByTestId(`settings-ai-save-ai.provider`);
  await providerSave.click();
  await expect(
    page.getByTestId("settings-ai-save-status-ai.provider"),
  ).toHaveText(/Saved/i, { timeout: 30_000 });

  // Persistence: the saved values become the database override, so the
  // effective source badge flips to "Database override" after a reload.
  await page.reload();
  await expect(page.getByTestId("settings-shell")).toBeVisible({
    timeout: 60_000,
  });
  await expandSection(page, "settings-ai");
  await expect(page.getByTestId("settings-ai-source-ai.provider")).toHaveText(
    /Database override/i,
    { timeout: 60_000 },
  );
  await expect(page.getByTestId("settings-ai-source-ai.model")).toHaveText(
    /Database override/i,
    { timeout: 60_000 },
  );

  // History records the model change.
  const historyRow = page
    .locator('[data-testid^="settings-ai-history-row-ai.model-"]')
    .first();
  await expect(historyRow).toBeVisible({ timeout: 60_000 });
  await expect(historyRow).toContainText(/\d{4}/);
});

test("pricing save with USD preview visible; invalid price input shows the rejection", async ({
  page,
  request,
}) => {
  await signInAsOperator(page, request);

  await page.goto("/operator/settings");
  await expect(page.getByTestId("settings-shell")).toBeVisible({
    timeout: 60_000,
  });
  await expandSection(page, "settings-ai");
  // Wait for the AI section to finish loading before interacting with its
  // fields (mount-time parse of the pricing table must settle first).
  await page.getByTestId("settings-ai-loading").waitFor({
    state: "hidden",
    timeout: 60_000,
  });
  await page.getByTestId("settings-ai-provider-select").waitFor({
    state: "visible",
    timeout: 60_000,
  });
  await page
    .getByTestId("settings-ai-provider-select")
    .selectOption(PROVIDER_OPENAI);
  await page
    .getByTestId("settings-ai-model-select")
    .locator(`option[value="${MODEL_OPENAI}"]`)
    .waitFor({ state: "attached", timeout: 30_000 });
  await page.getByTestId("settings-ai-model-select").selectOption(MODEL_OPENAI);

  const pricing = page.getByTestId("settings-ai-pricing-table");
  const preview = page.getByTestId(
    `settings-ai-pricing-preview-${MODEL_OPENAI}`,
  );

  // Valid pricing: preview shows USD per 1M tokens.
  await pricing.fill(`${MODEL_OPENAI}:100:200`);
  await expect(preview).toBeVisible({ timeout: 30_000 });
  await expect(preview).toContainText("USD per 1M tokens");
  await expect(preview).toContainText(MODEL_OPENAI);

  await page.getByTestId(`settings-ai-save-ai.pricing_table`).click();
  await expect(
    page.getByTestId("settings-ai-save-status-ai.pricing_table"),
  ).toHaveText(/Saved/i, { timeout: 30_000 });

  // Invalid price input: preview shows the rejection, no USD value.
  await pricing.fill(`${MODEL_OPENAI}:abc:200`);
  await expect(preview).toContainText("rates must be non-negative numbers");
  await expect(preview).not.toContainText("USD per 1M tokens");
});

test("key status label renders without revealing key material", async ({
  page,
  request,
}) => {
  await signInAsOperator(page, request);

  await page.goto("/operator/settings");
  await expect(page.getByTestId("settings-shell")).toBeVisible({
    timeout: 60_000,
  });
  await expandSection(page, "settings-ai");
  await page.getByTestId("settings-ai-provider-select").waitFor({
    state: "visible",
    timeout: 60_000,
  });
  await page
    .getByTestId("settings-ai-provider-select")
    .selectOption(PROVIDER_OPENAI);
  const keyStatus = page.getByTestId("settings-ai-api-key-status");
  await expect(keyStatus).toBeVisible({ timeout: 30_000 });
  await expect(keyStatus).toHaveText(
    /^(From environment|Not configured|Configured)/,
  );

  // No API key material is exposed anywhere on the page.
  await expect(page.getByTestId("settings-ai-api-key-input")).toBeVisible();
  const pageText = await page.textContent("body");
  expect(pageText).not.toMatch(/sk-[A-Za-z0-9]{20,}|AI_API_KEY\s*=\s*\S+/);
});
