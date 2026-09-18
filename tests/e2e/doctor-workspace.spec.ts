// Doctor review-workspace regression spec (ticket #476).
//
// The two doctor workspace pages (/doctor/review/[intakeId] and
// /doctor/cases/[caseId]) used to read the dynamic route segment synchronously
// from the `params` prop. On Next 16 that prop is a Promise, so the sync read
// yielded undefined -> Number(undefined) = NaN -> the initial load fetched
// /v1/intake/NaN/pre-summary/review and rendered the load-error banner instead
// of the workspace. This journey rides the REAL Next 16 runtime over the live
// backend and proves an active doctor can open an assigned intake's review
// workspace and see it render with requests that target the integer id - never
// /NaN/.
//
// The journey needs a real active doctor (operator activation), a real intake
// that reached ready_for_review (the structuring pipeline), and an assignment
// (patient pick). Since the ticket stays frontend-only, the event flow is
// driven through the app's OWN surface:
//   - the bootstrap operator + demo identity are seeded at backend boot
//     (scripts/e2e-backend.cjs runs seed_demo.py), and the operating TOTP
//     secret is stashed in apps/backend/var/e2e-bootstrap-operator.json; the
//     seeded operator identity is [Unverified] (invite path), so the spec
//     activates it through the app's own register+verify OTP flow before the
//     authenticated operator login;
//   - DISPATCHER_IN_PROCESS_ENABLED=true (playwright.config.ts) lets the
//     outbox dispatcher advance partner.activated (role grant), intake.captured
//     (pipeline -> ready_for_review) and pre_summary.ready (care case birth);
//   - mock AI (default in test) yields a clean 0.8-confidence pre-summary, so
//     the review is not forced and the workspace renders.
//
// Prior art: tests/e2e/auth-loop.spec.ts (partner wizard + staff login legs,
// mock-OTP read-back), tests/e2e/patient-journey.spec.ts (live backend API).
// Serial mode: the three tests share one doctor phone, one patient phone, one
// intake and one capture of the doctor's partner id; each test gets its own
// browser context so sessions do not leak.

import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from "@playwright/test";
import { createHmac } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

test.describe.configure({ mode: "serial" });
test.setTimeout(180_000);

const FRONTEND = "http://localhost:3000";
const BACKEND = "http://localhost:8000";
const BOOTSTRAP_OPERATOR_PHONE = "+919000000002";
const SEED_INFO_PATH = path.join(
  process.cwd(),
  "apps",
  "backend",
  "var",
  "e2e-bootstrap-operator.json",
);

function randomPhone(): string {
  return `9${String(Math.floor(Math.random() * 1_000_000_000)).padStart(
    9,
    "0",
  )}`;
}

const doctorPhone = randomPhone();
const patientPhone = randomPhone();

// Captured by test 1 from the register response and used by tests 2 + 3: the
// SAME partner the wizard created, so the operator decision and the patient
// pick resolve to the doctor this journey actually registered.
let doctorPartnerId: number | null = null;
// The intake the patient submits and the doctor opens, created by test 2.
let intakeId: number | null = null;

interface BootstrapSeedInfo {
  phone: string;
  totp_secret: string;
}

// The e2e backend boot writes the bootstrap operator's MFA facts here
// (scripts/e2e-backend.cjs). Read them once at the operator leg so a fresh
// boot always refreshes the attestation.
function readBootstrapSeedInfo(): BootstrapSeedInfo {
  if (!fs.existsSync(SEED_INFO_PATH)) {
    throw new Error(
      `missing ${SEED_INFO_PATH} - restart the e2e backend boot so seed_demo.py ` +
        "stashes the bootstrap operator's MFA facts",
    );
  }
  return JSON.parse(
    fs.readFileSync(SEED_INFO_PATH, "utf8"),
  ) as BootstrapSeedInfo;
}

// ---- RFC 6238 TOTP, no external deps (node:crypto only) ----

function base32Decode(input: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const clean = input.toUpperCase().replace(/[\s=]/g, "");
  let out = Buffer.alloc(0);
  let buffer = 0n;
  let bits = 0n;
  for (const char of clean) {
    const index = alphabet.indexOf(char);
    if (index === -1) {
      throw new Error(`invalid base32 character ${JSON.stringify(char)}`);
    }
    buffer = (buffer << 5n) | BigInt(index);
    bits += 5n;
    if (bits >= 8n) {
      bits -= 8n;
      out = Buffer.concat([out, Buffer.from([Number(buffer >> bits) & 0xff])]);
      buffer &= (1n << bits) - 1n;
    }
  }
  return out;
}

function totpCode(secret: string, windowOffset = 0): string {
  const counter = Math.floor(Date.now() / 1000 / 30) + windowOffset;
  const counterBytes = Buffer.alloc(8);
  counterBytes.writeBigUInt64BE(BigInt(counter));
  const digest = createHmac("sha1", base32Decode(secret))
    .update(counterBytes)
    .digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const binary =
    ((digest[offset] & 0x7f) << 24) |
    ((digest[offset + 1] << 16) |
      (digest[offset + 2] << 8) |
      digest[offset + 3]);
  return String(binary % 1_000_000).padStart(6, "0");
}

// ---- Shared HTTP helpers ----

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

function bearer(jwt: string): Record<string, string> {
  return { Authorization: `Bearer ${jwt}` };
}

async function operatorLogin(
  request: APIRequestContext,
  secret: string,
): Promise<string> {
  // The seeded bootstrap operator arrives on the invite path: identity status
  // [Unverified] with the operator role + MFA already enrolled. The operator
  // session gate (issue_operator_session) requires an ACTIVE identity, and the
  // only surface that flips an identity to Active is the app's own OTP
  // register+verify flow - so drive that first (idempotent: an existing phone
  // re-registers then verifies into the same identity).
  await registerPatient(request, "9000000002");

  // Try the current TOTP window, then the neighbours, to absorb a window
  // boundary crossing between code derivation and the login call.
  for (const windowOffset of [0, 1, -1]) {
    const response = await request.post(`${BACKEND}/v1/auth/operator/login`, {
      data: {
        phone: BOOTSTRAP_OPERATOR_PHONE,
        code: totpCode(secret, windowOffset),
      },
    });
    if (response.status() === 200) {
      const body = (await response.json()) as { jwt: string };
      return body.jwt;
    }
  }
  throw new Error(
    `operator MFA login refused (wrong TOTP or stale seed in ${SEED_INFO_PATH})`,
  );
}

async function registerPatient(
  request: APIRequestContext,
  number: string,
): Promise<string> {
  const phone = `+91${number}`;
  const register = await request.post(`${BACKEND}/v1/auth/register`, {
    data: { phone },
  });
  expect(register.status(), "patient register should succeed").toBe(200);
  const otp = await readMockOtp(request, number);
  const verify = await request.post(`${BACKEND}/v1/auth/verify`, {
    data: { phone, otp },
  });
  expect(verify.status(), "patient OTP verify should succeed").toBe(200);
  const session = await request.post(`${BACKEND}/v1/auth/session`, {
    data: { phone },
  });
  expect(session.status(), "patient session should mint").toBe(200);
  const body = (await session.json()) as { jwt: string };
  return body.jwt;
}

// ---- Test 1: register the doctor through the staff wizard ----

// The staff wizard's register POST returns the created partner's id; capture it
// so later tests activate and assign the SAME partner.
function capturePartnerId(page: Page): Promise<number> {
  return new Promise<number>((resolve) => {
    page.on("response", async (response) => {
      if (
        /\/v1\/partner\/register$/.test(response.url()) &&
        response.request().method() === "POST" &&
        response.ok()
      ) {
        const body = (await response.json()) as { partner_id?: number };
        if (typeof body.partner_id === "number") {
          resolve(body.partner_id);
        }
      }
    });
  });
}

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

test("a doctor registers through the staff wizard and the partner id is captured", async ({
  page,
  request,
}) => {
  const partnerIdPromise = capturePartnerId(page);
  await startPartnerRegistration(page, doctorPhone);
  await confirmPartnerPhone(page, request, doctorPhone);
  await expect(page).toHaveURL(`${FRONTEND}/partner/status/pending`);

  doctorPartnerId = await partnerIdPromise;
  expect(
    doctorPartnerId,
    "the register response must carry the created partner id",
  ).not.toBeNull();
});

// ---- Test 2: operator activates the doctor; patient assigns an intake ----

test("the operator activates the doctor and the patient assigns an intake to them", async ({
  request,
}) => {
  expect(
    doctorPartnerId,
    "the previous test must have registered the doctor first",
  ).not.toBeNull();

  // Operator leg: real TOTP second factor against the seeded bootstrap operator.
  const seed = readBootstrapSeedInfo();
  const operatorJwt = await operatorLogin(request, seed.totp_secret);
  const decision = await request.post(
    `${BACKEND}/v1/partner/verification/${doctorPartnerId}/decision`,
    {
      headers: bearer(operatorJwt),
      data: { approve: true },
    },
  );
  expect(
    decision.status(),
    "the operator decision must activate the doctor",
  ).toBe(200);

  // Patient leg: submit a text intake through the real API and wait for the
  // structuring pipeline (dispatcher + mock AI) to reach ready_for_review.
  const patientJwt = await registerPatient(request, patientPhone);

  // The structuring pipeline is consent-gated (fail-closed): without a live
  // grant on the AI egress lineage the intake degrades to raw doctor review -
  // no pre-summary is produced and the review queue stays empty. Mirror the
  // production onboarding grant (counterparty doctor / intake-ai /
  // consultations) before submitting so the pipeline actually structures.
  const consentGrant = await request.post(`${BACKEND}/v1/consents`, {
    headers: bearer(patientJwt),
    data: {
      counterparty_type: "doctor",
      counterparty_id: "intake-ai",
      record_scope: "consultations",
    },
  });
  expect(
    consentGrant.status(),
    "the patent consent grant must mint the AI egress lineage",
  ).toBe(201);

  const submit = await request.post(`${BACKEND}/v1/intake/submit`, {
    headers: bearer(patientJwt),
    data: {
      mode: "text",
      language: "en",
      text: "Fever and dry cough since three days, mild headache, no chest pain.",
    },
  });
  expect(submit.status(), "intake submit should succeed").toBe(200);
  const submitted = (await submit.json()) as { intake_id: number };
  intakeId = submitted.intake_id;
  expect(intakeId).not.toBeNull();

  await expect
    .poll(
      async () => {
        const status = await request.get(`${BACKEND}/v1/intake/${intakeId}`, {
          headers: bearer(patientJwt),
        });
        if (status.status() !== 200) {
          return null;
        }
        const body = (await status.json()) as { status?: string };
        return body.status ?? null;
      },
      {
        message: `intake ${intakeId} should reach ready_for_review`,
        timeout: 45_000,
        intervals: [1_000],
      },
    )
    .toBe("ready_for_review");

  // Assignment: the patient picks the now-active doctor. The pick gate checks
  // the doctor's Active/verified state, so a couple of retries absorb any
  // post-approval visibility lag.
  await expect
    .poll(
      async () => {
        const pick = await request.post(
          `${BACKEND}/v1/intake/${intakeId}/pick-doctor`,
          {
            headers: bearer(patientJwt),
            data: { partner_id: doctorPartnerId },
          },
        );
        return pick.status();
      },
      {
        message: `pick-doctor should accept the active doctor (partner ${doctorPartnerId})`,
        timeout: 30_000,
        intervals: [1_500],
      },
    )
    .toBe(200);
});

// ---- Test 3: the doctor opens the review workspace on the real runtime ----

async function activeDoctorLogin(
  page: Page,
  request: APIRequestContext,
  number: string,
): Promise<void> {
  await page.goto("/staff/login");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible({
    timeout: 60_000,
  });

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
  await page.waitForURL("**/doctor", { timeout: 60_000 });
  await expect(page.getByTestId("review-queue")).toBeVisible({
    timeout: 60_000,
  });
}

test("the active doctor lands on /doctor and the review workspace renders with integer ids", async ({
  page,
  request,
}) => {
  expect(
    intakeId,
    "the previous test must have submitted and assigned the intake",
  ).not.toBeNull();

  // Regression surface: watch every request this browser makes and record any
  // that would only happen if the route id had been read as NaN.
  const nanRequests: string[] = [];
  const reviewRequests: string[] = [];
  page.on("request", (req) => {
    const url = req.url();
    if (url.includes("/v1/intake/NaN/") || url.includes("/v1/care/cases/NaN")) {
      nanRequests.push(url);
    }
    if (/\/v1\/intake\/\d+\/pre-summary\/review$/.test(url)) {
      reviewRequests.push(url);
    }
  });

  await activeDoctorLogin(page, request, doctorPhone);

  // The assigned intake must appear in the review queue, linked to the exact
  // /doctor/review/{id} route.
  const reviewLink = page.getByTestId("queue-item-review").first();
  await expect(reviewLink).toBeVisible({ timeout: 30_000 });
  await expect(reviewLink).toHaveAttribute(
    "href",
    `/doctor/review/${intakeId}`,
  );
  await reviewLink.click();
  await page.waitForURL(`**/doctor/review/${intakeId}`);

  // The workspace must render - the pre-next-16 contract this ticket restores -
  // with no load-error banner and no NaN-targeted requests behind it.
  await expect(page.getByTestId("workspace-content")).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByTestId("error-banner")).toHaveCount(0, {
    timeout: 5_000,
  });
  expect(nanRequests, "no API request may target a NaN route id").toEqual([]);
  expect(
    reviewRequests.length,
    "the workspace must have loaded the review pre-summary",
  ).toBeGreaterThan(0);
  expect(
    reviewRequests.some((url) =>
      url.includes(`/v1/intake/${intakeId}/pre-summary/review`),
    ),
    "the review read must target the integer intake id from the URL",
  ).toBe(true);

  // Deep-link / hard-refresh (user story 5): reloading the same URL must land
  // on the same loaded workspace, never a transient parse failure.
  await page.reload();
  await expect(page.getByTestId("workspace-content")).toBeVisible({
    timeout: 60_000,
  });
  await expect(page.getByTestId("error-banner")).toHaveCount(0, {
    timeout: 5_000,
  });
  expect(
    nanRequests,
    "a hard refresh must not mint NaN requests either",
  ).toEqual([]);
});
