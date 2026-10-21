// Operator console navigation across the redesigned sidebar (ticket #756).
//
// #744 moved the operator console's nine sub-destinations into ONE nav-config
// group, and #745/#746 read that group from two surfaces: the desktop sidebar
// (a disclosure group, or a flyout from the collapsed icon rail) and the phone
// More sheet. This spec is the acceptance proof for that move on the real
// runtime - a real operator signs in through the app's own staff form and
// reaches every console destination from every surface the redesign added.
//
// It rides the live backend rather than a stub:
//   - the seeded bootstrap operator (scripts/e2e-backend.cjs -> seed_demo.py)
//     arrives on the invite path with identity status [Unverified], and the
//     operator session gate needs an ACTIVE identity, so the spec activates it
//     through the app's own register+verify OTP flow first - the same
//     activation the doctor-workspace spec drives;
//   - the operator's TOTP secret is read from the runtime fixture the backend
//     boot writes (apps/backend/var/e2e-bootstrap-operator.json), so a fresh
//     boot never leaves the spec holding a stale secret.
//
// The activation is deliberately tolerant: another spec may drive the same
// seeded phone (the doctor-workspace spec does), so the OTP challenge can
// already be spent by the time this spec reads it back. What the operator
// session actually needs is an ACTIVE identity, and that is what the spec
// asserts - the session mint is the proof, not the challenge's fate.
//
// Serial mode: the legs share the one seeded operator phone, and the operator
// identity has to be Active before any leg can sign in.
//
// Prior art: tests/e2e/doctor-workspace.spec.ts (operator activation + the
// RFC 6238 TOTP derivation), tests/e2e/auth-loop.spec.ts (staff login legs).

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
// Nine destinations per leg, each one a route the dev server compiles on first
// request: the network drive this repo lives on makes that slow.
test.setTimeout(360_000);

// ---- The console's destinations (#744) ----

interface Destination {
  /** The nav-config key: the sidebar row, the flyout row and the sheet row. */
  key: string;
  href: string;
  /** The page's own h1. */
  heading: string;
  /** The panels the page must render, so "reached" is not "a blank shell". */
  panels: string[];
}

// Settings is the #747 placeholder shell: it carries no panel of its own, so
// its empty state is the surface that proves the page rendered.
//
// The Overview's KPI row is NOT one of them: that row is mounted only while
// the read is in flight or when telemetry exists, and a deployment the nightly
// rollup has never covered shows "No telemetry yet" instead. The alert feed
// and the deep-links panel render in every state, so they are what proves the
// Overview page rendered rather than blanked.
const DESTINATIONS: Destination[] = [
  {
    key: "overview",
    href: "/operator/observability",
    heading: "Observability",
    panels: ["observability-alerts", "observability-deeplinks"],
  },
  {
    key: "business",
    href: "/operator/observability/business",
    heading: "Business",
    panels: [
      "business-spend",
      "business-breakdown",
      "business-unit-costs",
      "business-margin",
      "business-heavy-actors",
    ],
  },
  {
    key: "product",
    href: "/operator/observability/product",
    heading: "Product",
    panels: ["product-active-users", "product-funnel", "product-retention"],
  },
  {
    key: "reliability",
    href: "/operator/observability/reliability",
    heading: "Reliability",
    panels: [
      "reliability-providers",
      "reliability-error-feed",
      "reliability-throughput",
      "reliability-queues",
      "reliability-concurrency",
    ],
  },
  {
    key: "cost",
    href: "/operator/observability/cost",
    heading: "AI cost",
    panels: ["cost-budget", "cost-trend"],
  },
  {
    key: "usage",
    href: "/operator/observability/usage",
    heading: "AI usage",
    panels: ["usage-breakdown"],
  },
  {
    key: "quality",
    href: "/operator/observability/quality",
    heading: "AI quality",
    panels: ["quality-report"],
  },
  {
    key: "health",
    href: "/operator/observability/health",
    heading: "System health",
    panels: ["health-latency", "health-system"],
  },
  {
    key: "settings",
    href: "/operator/observability/settings",
    heading: "Settings",
    panels: ["empty-state"],
  },
];

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// ---- Backend helpers ----

// Flip the seeded operator identity to Active through the app's own OTP flow.
// The operator session gate (issue_operator_session) needs an ACTIVE identity,
// and the only surface that flips one is register+verify.
//
// The session mint is the assertion, not the challenge: it answers 200 only
// for an Active identity that holds an active patient role grant, which is
// exactly the state the operator login needs. The mint is also the cheap
// probe: when the identity is already Active - another spec activated it, or
// an earlier leg did - there is nothing to flip, so no challenge is issued
// and none is spent.
//
// When the identity is not Active yet, this spec does have to drive the
// challenge, and it shares the seeded phone with doctor-workspace.spec.ts:
// the challenge is latest-wins, so the two files can invalidate each other's.
// The retry below absorbs that - the phone settles once the other spec has
// spent or released its challenge.
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
    // The challenge could not be spent (another spec holds it, or the resend
    // cooldown blocks a fresh one): give the phone room before trying again.
    await new Promise((resolve) => setTimeout(resolve, 20_000));
  }

  throw new Error(
    "operator identity never became Active (OTP verified) so it cannot sign in",
  );
}

// ---- Sign-in ----

// The operator form's inputs are React-controlled. Filling one before the
// client bundle has hydrated leaves the DOM value outside React's state, and
// the first render after hydration wipes it - the field comes back empty and
// the submit is refused by the client-side check instead of reaching the API.
// The blur handler is client-side behaviour, so a field error is the proof
// that React is listening.
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

// Whatever the form said about the last attempt, read with a bounded wait: a
// refused login can report through the envelope notice or through the field
// summary, and neither is guaranteed to be there.
async function readRefusal(page: Page): Promise<string> {
  for (const testId of ["staff-login-error", "staff-form-summary"]) {
    const text = await page
      .getByTestId(testId)
      .textContent({ timeout: 2_000 })
      .catch(() => null);
    if (text !== null) {
      return `${testId}: ${text.trim()}`;
    }
  }
  return "no error notice";
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

  // The national form the form accepts: the backend normalizes it to the
  // seeded +919000000002 (a 12-digit national number is not a phone).
  const phoneField = page.getByTestId("staff-phone");
  const totpField = page.getByTestId("staff-totp");

  // The server accepts one TOTP step of drift either side of now, but the
  // code is derived here and typed there: if the step turns over between the
  // two, the neighbouring windows are tried in turn.
  let refusal = "no error notice";
  for (const windowOffset of [0, 1, -1]) {
    await phoneField.fill("9000000002");
    await totpField.fill(totpCode(seed.totp_secret, windowOffset));
    await page.getByTestId("staff-submit").click();

    // A refused login answers in a notice; a landed one navigates away.
    const refused = await page
      .getByTestId("staff-login-error")
      .waitFor({ state: "visible", timeout: 5_000 })
      .then(() => true)
      .catch(() => false);
    if (refused) {
      refusal = await readRefusal(page);
      continue;
    }

    try {
      // The console compiles on first request in dev, so the landing can take
      // a while on a cold server.
      await page.waitForURL(/\/operator(\?|$)/, { timeout: 60_000 });
      return;
    } catch {
      refusal = await readRefusal(page);
    }
  }
  throw new Error(
    `operator sign-in failed for every TOTP window (stale seed or refused ` +
      `credentials): ${refusal}`,
  );
}

// ---- Dev-server warm-up ----

// The dev server compiles a route the first time something requests it, and
// the compile pushes a Fast Refresh update that cancels the client-side
// navigation that triggered it: a nav click that lands on a cold route never
// commits, so the URL never moves and the click looks broken. Warming every
// console route first (one page each, in parallel) turns the later nav clicks
// into real client-side navigations.
//
// The warm-up asserts nothing and proves nothing about the nav: it only pays
// the dev server's per-route compile so the clicks below are judged on the
// nav and not on Turbopack's first-compile behaviour.
async function warmConsoleRoutes(page: Page): Promise<void> {
  const context = page.context();
  const warmPages = await Promise.all(
    DESTINATIONS.map(() => context.newPage()),
  );
  try {
    await Promise.all(
      warmPages.map((warmPage, index) =>
        warmPage.goto(DESTINATIONS[index].href, { timeout: 300_000 }),
      ),
    );
  } finally {
    await Promise.all(warmPages.map((warmPage) => warmPage.close()));
  }
}

// The warm-up needs an authenticated context, so it signs in through the same
// staff form the tests use. The session lives in the context (localStorage and
// the presence-hint cookie), so every warm-up page inherits it.
test.beforeAll(async ({ browser }) => {
  test.setTimeout(900_000);
  const context = await browser.newContext();
  try {
    const page = await context.newPage();
    await signInAsOperator(page, context.request);
    await warmConsoleRoutes(page);
  } finally {
    await context.close();
  }
});

// ---- Shared assertions ----

async function expectDestination(
  page: Page,
  destination: Destination,
): Promise<void> {
  await expect(page, `${destination.key} should be the open route`).toHaveURL(
    new RegExp(`${escapeRegExp(destination.href)}$`),
    // The dev server compiles a route on its first request, and the URL only
    // moves when the navigation commits, so this wait is not instant.
    { timeout: 60_000 },
  );
  await expect(
    page.getByRole("heading", { level: 1, name: destination.heading }),
    `${destination.key} should render its own heading`,
  ).toBeVisible({ timeout: 60_000 });
  for (const panel of destination.panels) {
    await expect(
      page.getByTestId(panel),
      `${destination.key} should render the ${panel} panel`,
    ).toBeVisible({ timeout: 60_000 });
  }
}

// The expanded sidebar keeps the group in a disclosure: closed on arrival (the
// operator lands on the verification queue) and opened by its header.
async function openObservabilityGroup(page: Page): Promise<void> {
  const header = page.getByTestId("nav-observability");
  await expect(header).toBeVisible({ timeout: 60_000 });
  if ((await header.getAttribute("aria-expanded")) !== "true") {
    await header.click();
  }
  await expect(header).toHaveAttribute("aria-expanded", "true");
}

async function openMoreSheet(page: Page): Promise<void> {
  await expect(page.getByTestId("more-sheet")).toBeHidden();
  await page.getByTestId("more-trigger").click();
  await expect(page.getByTestId("more-sheet")).toBeVisible({ timeout: 30_000 });
}

// ---- Desktop: the redesigned sidebar ----

test.describe("operator console navigation (desktop sidebar)", () => {
  test.use({ viewport: { width: 1440, height: 900 } });

  test("the expanded sidebar reaches every console destination", async ({
    page,
    request,
  }) => {
    await signInAsOperator(page, request);

    const sidebar = page.getByTestId("sidebar");
    await expect(sidebar).toBeVisible({ timeout: 60_000 });
    await expect(sidebar).not.toHaveAttribute("data-collapsed", "true");
    // The phone bar belongs to the small breakpoint only.
    await expect(page.getByTestId("bottom-tabs")).toBeHidden();

    await openObservabilityGroup(page);

    for (const destination of DESTINATIONS) {
      await openObservabilityGroup(page);
      await page.getByTestId(`nav-${destination.key}`).click();
      await expectDestination(page, destination);
    }
  });

  test("the collapsed icon rail still reaches the console group", async ({
    page,
    request,
  }) => {
    await signInAsOperator(page, request);

    await page.getByTestId("sidebar-toggle").click();
    const sidebar = page.getByTestId("sidebar");
    await expect(sidebar).toHaveAttribute("data-collapsed", "true");

    // Collapsed, the group is an icon whose flyout lists every
    // sub-destination - the group must not become unreachable.
    const group = page.getByTestId("sidebar-group-observability-collapsed");
    await expect(group).toBeVisible();

    // Hovering the icon opens the flyout, and the flyout offers every
    // sub-destination with the group's own hrefs: the collapsed rail is a way
    // into the group, not a dead end.
    await group.hover();
    const flyout = page.getByTestId("sidebar-flyout");
    await expect(flyout).toBeVisible({ timeout: 30_000 });
    for (const destination of DESTINATIONS) {
      await expect(
        flyout.getByTestId(`nav-${destination.key}`),
        `the flyout should offer ${destination.key}`,
      ).toHaveAttribute("href", destination.href);
    }

    // Clicking through the flyout reaches a destination - the awkward path
    // the brief calls out. The click runs from the queue page the operator
    // lands on: on the chart pages the flyout's lower rows are painted under
    // the page content (#758), so there they are covered rather than clickable.
    await group.hover();
    await flyout.getByTestId("nav-business").click();
    await expectDestination(page, DESTINATIONS[1]);

    // And the group's own icon is the rail's way in.
    await group.getByTestId("nav-observability").click();
    await expectDestination(page, DESTINATIONS[0]);
  });
});

// ---- Phone: the More sheet ----

test.describe("operator console navigation (phone More sheet)", () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test("the More sheet reaches every console sub-destination", async ({
    page,
    request,
  }) => {
    await signInAsOperator(page, request);

    // The sidebar leaves the layout below the lg breakpoint; the sheet is the
    // phone's route into the console group.
    await expect(page.getByTestId("sidebar")).toBeHidden();
    await expect(page.getByTestId("bottom-tabs")).toBeVisible({
      timeout: 60_000,
    });

    for (const destination of DESTINATIONS) {
      await openMoreSheet(page);
      await page.getByTestId(`more-${destination.key}`).click();
      await expectDestination(page, destination);
      // The sheet closes on the way out, so the next leg opens it again.
      await expect(page.getByTestId("more-sheet")).toBeHidden();
    }
  });
});
