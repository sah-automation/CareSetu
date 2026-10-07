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
// The fourth link (#621) rides the same activated doctor: it drives the profile
// page's own per-section writes (FEAT-005) and then reads the PUBLIC provider
// profile, so the declared fields are asserted on the surface a patient sees
// rather than on the console that wrote them.
//
// The fifth link (#661) closes the review's e2e gap on the corrected doctor
// lists: /doctor/patients and /doctor/cases each render a real card from the
// live list APIs (FEAT-008, spec #645), and each card navigates to its detail
// surface - the row->detail journey no page suite can prove.
//
// Prior art: tests/e2e/auth-loop.spec.ts (partner wizard + staff login legs,
// mock-OTP read-back), tests/e2e/patient-journey.spec.ts (live backend API).
// Serial mode: the five tests share one doctor phone, one patient phone, one
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

// ---- Test 4: the doctor declares their address; the public profile shows it ----

// FEAT-005 (#621): the profile flow, end to end, on the real runtime.
//
// The three links above leave an `[Active]` doctor with a verified credential and a
// listed directory entry - which is exactly the visibility gate the PUBLIC provider
// profile enforces (ADR-0011 "tick gone = card gone"). So this link needs no new
// setup: it logs the same doctor back in and drives the profile page's own per-
// section writes, then reads the result on the patient-facing route.
//
// What it proves:
//   1. an active doctor lands on /doctor/profile and the page renders its sections
//      - with no coordinate input anywhere to declare instead;
//   2. the practice section saves the clinic name and the specialty selection;
//   3. the structured address saves, and the save says so;
//   4. an unplaceable PIN reports under the PIN input, and the refusal does not
//      poison the page - a DIFFERENT section still saves;
//   5. the public profile then shows what the doctor just declared.
//
// Two PINs, chosen so the test exercises the branch it means to. `RESOLVABLE_PIN` is
// in the bundled centroid dataset (`apps/backend/alembic/versions/pin_centroids.csv.gz`,
// a Palamu delivery office), which is the only table that decides "placeable".
// `UNRESOLVABLE_PIN` is well formed - six ASCII digits, so the CLIENT's
// `PIN_CODE_PATTERN` accepts it and the refusal has to be the server's to give - and
// absent from that same dataset, so it fails as "cannot be placed" rather than as
// malformed. A malformed value would pass this test while proving nothing about the
// centroid lookup. Both are read off the committed dataset rather than guessed: a
// merely plausible PIN may not resolve, and the first save then fails for a reason
// that has nothing to do with this test.
const RESOLVABLE_PIN = "822101";
const UNRESOLVABLE_PIN = "822002";
const CLINIC_NAME = "E2E Riverside Clinic";
const ADDRESS_LINE = "12 Baghdar Road";
const LANDMARK = "Near the old post office";
const LOCALITY = "Baghdar";
const CITY = "Daltonganj";
const ABOUT =
  "I have run a small neighbourhood practice for twelve years and I still see every " +
  "patient myself.";

test("the doctor declares their address and the public profile shows what they declared", async ({
  page,
  request,
  browser,
}, testInfo) => {
  expect(
    doctorPartnerId,
    "the first test must have registered the doctor this link reads back",
  ).not.toBeNull();

  // The file-wide 180 s budget does not fit this link. The chain shares ONE phone
  // number across its four links, so this login can land inside the previous link's
  // 60 s SMS resend cooldown, and `activeDoctorLogin`'s cold path spends ~107 s
  // waiting that window out before the code is even readable. Raised here rather
  // than file-wide so the three links above keep the budget they already pass in.
  testInfo.setTimeout(300_000);

  // Log in FIRST. `proxy` matches `/doctor/:path*` and bounces any hit whose
  // `caresetu_authed` presence hint is missing or empty to the staff login, keeping
  // the original path in the return param - so a `goto("/doctor/profile")` before
  // the login lands would silently put every later locator on the wrong page.
  await activeDoctorLogin(page, request, doctorPhone);

  // --- AC 1: the profile page renders its sections ----------------------------
  await page.goto("/doctor/profile");
  // Assert the destination before the page's contents. A guard bounce lands on the
  // staff login with `/doctor/profile` in the return param, and every locator below
  // is built out of this page's own test ids - so without this, a bounce fails on
  // the first section assertion with a message about a section rather than about
  // never having arrived. Naming the URL turns the likeliest silent failure in this
  // link into the failure it actually is.
  await expect(page).toHaveURL(`${FRONTEND}/doctor/profile`);
  for (const section of [
    "profile-identity",
    "profile-section-index",
    "profile-verified-band",
    "profile-declared-band",
    "profile-practice-card",
    "profile-address-card",
    "profile-about-card",
    "profile-notification-card",
    "fee-editor",
    "profile-live-preview",
  ]) {
    await expect(
      page.getByTestId(section),
      `the profile page must render ${section}`,
    ).toBeVisible({ timeout: 60_000 });
  }

  // --- AC 5: no coordinate inputs --------------------------------------------
  // Count assertions on named locators rather than an absence check on a container,
  // so these cannot pass because the page failed to render - the card that owns the
  // address is asserted visible immediately above, and is used again below. Both the
  // retired test ids AND the accessible names are asserted, because the redesign
  // (#606/#616) removed the inputs and renamed what is left: an id this test
  // remembers is the weaker half of the pair, and the label is what would survive a
  // future rename of the ids.
  await expect(page.getByTestId("profile-latitude")).toHaveCount(0);
  await expect(page.getByTestId("profile-longitude")).toHaveCount(0);
  await expect(page.getByLabel(/latitude/i)).toHaveCount(0);
  await expect(page.getByLabel(/longitude/i)).toHaveCount(0);
  // And the card that owns the address carries no coordinate input at all, which is
  // where they used to live: the position is derived from the PIN (#603/#606), so a
  // coordinate input here would be a second, unsourced way to place the practice.
  await expect(
    page
      .getByTestId("profile-address-card")
      .locator('input[id*="latitude" i], input[id*="longitude" i]'),
  ).toHaveCount(0);

  // --- The practice section: clinic name + the specialty selection -------------
  // A section save declares its WHOLE card, and `full_name` is `min_length=1`, so
  // the registered name has to be standing in this input before the card can save.
  await expect(page.getByTestId("profile-practice-name")).not.toHaveValue("");

  await page.getByTestId("profile-practice-clinic").fill(CLINIC_NAME);
  // Chips are found by the SLUG of the machine value, not by their label: the label
  // is copy and differs per locale, while the slug is derived from the wire value.
  await page
    .getByTestId("profile-practice-specialties-general-physician")
    .click();
  await page.getByTestId("profile-practice-specialties-pediatrician").click();
  await page.getByTestId("profile-practice-save").click();
  await expect(page.getByTestId("profile-practice-saved")).toBeVisible({
    timeout: 30_000,
  });

  // --- AC 2: the structured address saves -------------------------------------
  for (const [testId, value] of [
    ["profile-address-line", ADDRESS_LINE],
    ["profile-address-landmark", LANDMARK],
    ["profile-address-locality", LOCALITY],
    ["profile-address-city", CITY],
    ["profile-address-pin", RESOLVABLE_PIN],
  ] as const) {
    await page.getByTestId(testId).fill(value);
  }
  await page.getByTestId("profile-address-save").click();
  await expect(page.getByTestId("profile-address-saved")).toBeVisible({
    timeout: 30_000,
  });

  // --- AC 3a: an unplaceable PIN reports under the PIN input ------------------
  await page.getByTestId("profile-address-pin").fill(UNRESOLVABLE_PIN);
  await page.getByTestId("profile-address-save").click();

  // Scoped to the address card: `profile-address-pin-error` is the line wired to
  // the input by `aria-describedby`, so "under the PIN input" is asserted as
  // (a) the card owns the line, (b) the input is flagged invalid, and (c) the input
  // is what describes itself with it.
  const addressCard = page.getByTestId("profile-address-card");
  const pinError = addressCard.getByTestId("profile-address-pin-error");
  await expect(
    pinError,
    "an unplaceable PIN must report under the PIN input",
  ).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("profile-address-pin")).toHaveAttribute(
    "aria-invalid",
    "true",
  );
  await expect(page.getByTestId("profile-address-pin")).toHaveAttribute(
    "aria-describedby",
    /profile-address-pin-error/,
  );
  // And the card must NOT claim it saved: a refused attempt is not a save.
  await expect(page.getByTestId("profile-address-saved")).toHaveCount(0);
  await expect(page.getByTestId("profile-address-unsaved")).toBeVisible();

  // --- AC 3b: a different section still saves afterwards ----------------------
  // The end-to-end counterpart of #605's per-section buffer rule, and the assertion
  // most likely to regress: a page-level buffer that had collapsed back into one
  // would strand the About card's edits behind the Address card's refusal.
  await page.getByTestId("profile-about").fill(ABOUT);
  await page.getByTestId("profile-about-save").click();
  await expect(page.getByTestId("profile-about-saved")).toBeVisible({
    timeout: 30_000,
  });
  // The refused card keeps its own unsaved edit, and the two sections report
  // independently - one refusal, one success, neither overwriting the other.
  await expect(page.getByTestId("profile-address-unsaved")).toBeVisible();
  await expect(page.getByTestId("profile-practice-saved")).toBeVisible();

  // --- AC 4: the PUBLIC profile shows what the doctor just declared -----------
  // A FRESH context, and that is the assertion, not an implementation detail: the
  // declared band is on the patient-facing page, so it has to be readable by a
  // context that never signed in and holds no session cookie at all. It also keeps
  // the dirty Address card's `beforeunload` guard out of the navigation - the
  // console page is left open rather than navigated away from.
  const patientContext = await browser.newContext();
  try {
    const patient = await patientContext.newPage();
    await patient.goto(`${FRONTEND}/providers/${doctorPartnerId}`);

    // The band #619 renders, and NOT the not-found / error states - the four gate
    // conditions the previous links earned by approving the doctor.
    await expect(patient.getByTestId("profile-not-found")).toHaveCount(0);
    await expect(patient.getByTestId("profile-error")).toHaveCount(0);
    const declaredBand = patient.getByTestId("profile-declared");
    await expect(declaredBand).toBeVisible({ timeout: 30_000 });

    // Scoped to the band: `profile-declared-clinic-name` and
    // `profile-declared-specialties` are the #619 locators, and reading them inside
    // the band says which surface this is rather than leaving it implied.
    await expect(
      declaredBand.getByTestId("profile-declared-clinic-name"),
    ).toHaveText(CLINIC_NAME, { timeout: 30_000 });

    const declaredSpecialties = declaredBand.getByTestId(
      "profile-declared-specialties",
    );
    await expect(declaredSpecialties).toContainText("General Physician", {
      timeout: 30_000,
    });
    await expect(declaredSpecialties).toContainText("Pediatrician", {
      timeout: 30_000,
    });

    // The address, part by part. The PIN that landed is the resolvable one: the
    // refused PIN never reached a column, so what the public page shows proves the
    // refusal wrote nothing. These ids are `profile-declared-address-` plus the
    // band's own FIELD name, and the field name is the address part's own name -
    // hence the doubled word in the line. Spelled out rather than composed, so the
    // doubling reads as deliberate instead of getting "fixed" into a locator that
    // matches nothing.
    const declaredAddress = declaredBand.getByTestId(
      "profile-declared-address",
    );
    await expect(declaredAddress).toBeVisible({ timeout: 30_000 });
    for (const [testId, value] of [
      ["profile-declared-address-address-line", ADDRESS_LINE],
      ["profile-declared-address-landmark", LANDMARK],
      ["profile-declared-address-locality", LOCALITY],
      ["profile-declared-address-city", CITY],
      ["profile-declared-address-pin-code", RESOLVABLE_PIN],
    ] as const) {
      await expect(declaredAddress.getByTestId(testId)).toHaveText(value, {
        timeout: 30_000,
      });
    }

    // And the About card's own words, which is the save the refused PIN was
    // supposed to be unable to block: prose the doctor typed reaches a patient
    // verbatim.
    await expect(declaredBand.getByTestId("profile-declared-about")).toHaveText(
      ABOUT,
      { timeout: 30_000 },
    );
  } finally {
    await patientContext.close();
  }
});

// ---- Test 5: the corrected doctor lists render their grids and navigate ----

// FEAT-008 (#651/#652/#655/#660, spec #645): the two lists the correction
// rebuilt on the shared card have no journey coverage - the links above ride
// the review workspace and the profile, never the grids themselves. This link
// proves, on the real backend:
//   1. /doctor/patients renders the patient who picked this doctor as a card -
//      worded name fallback, a real worded stage (the assigned case behind it),
//      and no NaN ids;
//   2. the card navigates to that patient's detail page;
//   3. /doctor/cases renders the care case born from the same intake, with the
//      server-assigned case id in the card's meta;
//   4. the case card navigates to the case workspace.
test("the doctor's patients and cases grids render and navigate to their detail pages", async ({
  page,
  request,
}) => {
  expect(
    intakeId,
    "the earlier links must have submitted, assigned and structured the intake",
  ).not.toBeNull();

  await activeDoctorLogin(page, request, doctorPhone);

  // ---- Patients grid ----
  await page.goto("/doctor/patients");
  const patientRow = page.getByTestId("patient-row").first();
  await expect(patientRow).toBeVisible({ timeout: 30_000 });

  // The journey's patient registered by phone only, so the row falls back to
  // the worded default - never a blank label and never a raw id (#660).
  await expect(page.getByTestId("patient-row-name").first()).toHaveText(
    "Patient",
  );

  // This patient has an assigned care case, so the stage chip must read a real
  // worded stage; "No open case" here would mean the case-to-patient link that
  // also drives the list's presence broke.
  const patientStage = page.getByTestId("patient-row-stage").first();
  await expect(patientStage).toBeVisible();
  await expect(patientStage).not.toHaveText("No open case");

  const patientOpen = page.getByTestId("patient-row-open").first();
  await expect(patientOpen).toHaveAttribute(
    "href",
    /^\/doctor\/patients\/\d+$/,
  );
  await patientOpen.click();
  await page.waitForURL(/\/doctor\/patients\/\d+/, { timeout: 30_000 });
  await expect(page.getByTestId("patient-header-band")).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByTestId("patient-detail-name")).toContainText(
    "Patient",
  );

  // ---- Cases grid ----
  await page.goto("/doctor/cases");
  const caseRow = page.getByTestId("case-item").first();
  await expect(caseRow).toBeVisible({ timeout: 30_000 });

  // The card's meta carries the server-assigned case id ("Case #<n>").
  await expect(page.getByTestId("case-item-id").first()).toContainText(
    "Case #",
  );

  const caseOpen = page.getByTestId("case-item-open").first();
  await expect(caseOpen).toHaveAttribute("href", /^\/doctor\/cases\/\d+$/);
  await caseOpen.click();
  await page.waitForURL(/\/doctor\/cases\/\d+/, { timeout: 30_000 });
  await expect(page.getByTestId("case-content")).toBeVisible({
    timeout: 60_000,
  });
});
