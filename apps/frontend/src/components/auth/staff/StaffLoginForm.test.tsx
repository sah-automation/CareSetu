// PHASE-2.6 T10 (#201): staff login card behavior (done-verify suite).
//
// PHASE-5 T4 (#282): operator login flow tests - phone+TOTP triggers
// operatorLogin, SESSION_MFA_REQUIRED surfaces TOTP step, successful MFA
// creates session and routes via postLoginTarget.
//
// PHASE-5 T7 (#467): partner mode is phone + SMS code for real (ADR-0016).
// The dead email/password fields and the Phase-5 notice are gone; the card
// drives /v1/auth/partner/login -> verify -> session, mirrors the patient
// wizard's phone->code->countdown->resend->demo-banner interaction, renders
// the partner refusals (no_account/cooldown/locked/suspended), and on success
// mints the partner session + routes through the same save/landing path as the
// operator flow - without ever touching the patient lifecycle.

import { readFileSync } from "node:fs";

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import StaffLoginPage from "@/app/staff/login/page";
import { ApiError } from "@/lib/api-errors";
import {
  AuthApiError,
  fetchDemoOtp,
  fetchMe,
  issuePartnerSession,
  issueSession,
  partnerLogin,
  partnerVerify,
  type PartnerLoginResult,
  type PartnerVerifyResult,
  type SessionResult,
  registerPhone,
  verifyOtp,
} from "@/lib/auth/api";
import { STRINGS } from "@/lib/i18n/dictionaries";
import type {
  PartnerMeView,
  PartnerStatus,
  PartnerType,
} from "@/lib/partner/api";

import { DONE_SCREEN_COUNTDOWN_SECONDS } from "../DoneScreen";
import atomStyles from "../otp/otpShared.module.css";
import { PrimaryButton } from "../otp/shared";
import stepStyles from "../otp/variantB.module.css";
import { StaffLoginForm, staffSubmitLabel } from "./StaffLoginForm";

const mockLocationReplace = vi.fn();
Object.defineProperty(window, "location", {
  value: { ...window.location, replace: mockLocationReplace },
  writable: true,
  configurable: true,
});

const mockOperatorLogin = vi.fn();
vi.mock("@/lib/operator/api", () => ({
  operatorLogin: (...args: unknown[]) => mockOperatorLogin(...args),
}));

vi.mock("@/lib/auth/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/auth/api")>();
  return {
    ...mod,
    fetchMe: vi.fn(),
    fetchDemoOtp: vi.fn(),
    issuePartnerSession: vi.fn(),
    issueSession: vi.fn(),
    registerPhone: vi.fn(),
    verifyOtp: vi.fn(),
    partnerLogin: vi.fn(),
    partnerVerify: vi.fn(),
  };
});

const mockSaveSession = vi.fn();
vi.mock("@/lib/auth/session", () => ({
  saveSession: (...args: unknown[]) => mockSaveSession(...args),
}));

// #537: the active-partner done screen resumes the saved session in-flow
// (same no-reload seam as the patient wizard, #496) before routing with the
// framework router.
const authState = vi.hoisted(() => ({
  resumeSession: vi.fn(),
}));

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: null,
    selectedRole: null,
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: false,
    isLoading: false,
    resumeSession: authState.resumeSession,
  }),
}));

const mockRouterReplace = vi.fn();
const stableRouter = { replace: mockRouterReplace };
// #566: the handoff's reported surface is the PAGE's - the sign-in heading it
// owns is one of the three things the reported flash leaves behind, and the page
// reads its own search params. `app/staff/login/page.test.tsx` owns the page's
// own render; the reason this suite also mounts the page is that the heading
// can only be counted against a document the handoff is inside, which means
// driving the real flow rather than rendering the form alone.
const stableSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => stableRouter,
  useSearchParams: () => stableSearchParams,
}));

const { mockFetchPartnerMe } = vi.hoisted(() => ({
  mockFetchPartnerMe: vi.fn(),
}));
vi.mock("@/lib/partner/api", () => ({
  fetchPartnerMe: (...args: unknown[]) => mockFetchPartnerMe(...args),
}));

const mockPostLoginTarget = vi.fn().mockReturnValue("/operator/home");
// #562: fetchPartnerRouteState is deliberately NOT replaced. It is the only
// caller of fetchPartnerMe, so stubbing it here left mockFetchPartnerMe as dead
// code the suite still asserted on, and left a route-state implementation that
// leaked between tests. Mocking the transport one level down (mockFetchPartnerMe
// above) keeps the reader production actually runs, and is the shape
// staff-routing.test.ts already pins.
vi.mock("@/lib/auth/staff-routing", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/auth/staff-routing")>();
  return {
    ...mod,
    postLoginTarget: (...args: unknown[]) => mockPostLoginTarget(...args),
  };
});

// #562 AC-2/AC-4: the uniform mock lifecycle, and the single mechanism that
// enforces it. vi.clearAllMocks drops call records only, so an implementation a
// test installed went on answering for the next one - which is how a partner
// route-state answer set by one test reached four others. resetAllMocks wipes
// implementations too, so no mock can be quietly omitted from a reset list.
//
// The consequence is deliberate: a mock with no answer installed is genuinely
// bare, and the suite says so rather than papering over it with a blanket
// default. The two "partner-status answer" tests in the partner code step are
// the ordering probe: the first installs an answer, the second installs none
// and asserts the reader degrades. Revert this block to clearAllMocks and that
// pair goes red.
afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  // #566: the countdown test fakes the tick only; without this the fake
  // interval would outlive the suite it was installed for.
  vi.useRealTimers();
  vi.resetAllMocks();
});

// Declares the defaults a test may rely on without restating them. No resets
// here: the afterEach above already guarantees a bare mock, and a second reset
// list is the list things get forgotten from.
beforeEach(() => {
  // Default: the seam settles immediately (the app awaits it before routing).
  authState.resumeSession.mockResolvedValue(undefined);
  mockPostLoginTarget.mockReturnValue("/operator/home");
  // No default for mockFetchPartnerMe: every test that reads partner status
  // states the answer it means, and a test that does not is genuinely reading
  // "no answer" - the case the ordering probe below asserts.
});

const t = STRINGS.en.staffAuth.login;

const PHONE = "+919876543210";

const LOGIN_OK: PartnerLoginResult = {
  outcome: "sent",
  phone_e164: PHONE,
  challenge_id: 21,
  expires_in_seconds: 300,
  cooldown_remaining_seconds: 60,
  attempts_left: 5,
  lockout_remaining_seconds: null,
};

const SESSION: SessionResult = {
  jwt: "header.payload.signature",
  jti: "jti-1",
  scope: "partner",
  identity_id: 7,
  expires_in_seconds: 900,
  refresh_token: "opaque-refresh-token",
};

// The refusal the code step's message arms all read from. Declared once so a
// test says what it is about rather than restating the shape.
const WRONG_CODE: PartnerVerifyResult = {
  outcome: "wrong_code",
  phone_e164: PHONE,
  identity_id: null,
  attempts_left: 4,
  lockout_remaining_seconds: null,
};

function typePartnerPhone(digits = "9876543210") {
  fireEvent.change(screen.getByTestId("partner-phone"), {
    target: { value: digits },
  });
}

function typeCode(digits = "123456") {
  fireEvent.change(screen.getByTestId("partner-otp"), {
    target: { value: digits },
  });
}

function typeCodeAndSubmit(digits = "123456") {
  typeCode(digits);
  fireEvent.click(screen.getByTestId("staff-submit"));
}

async function startPartnerOtpFlow(loginResult: PartnerLoginResult = LOGIN_OK) {
  vi.mocked(partnerLogin).mockResolvedValue(loginResult);
  render(<StaffLoginForm />);
  typePartnerPhone();
  fireEvent.click(screen.getByTestId("staff-submit"));
  await screen.findByTestId("partner-otp");
}

function fillPhoneAndTotp() {
  fireEvent.change(screen.getByTestId("staff-phone"), {
    target: { value: "9876543210" },
  });
  fireEvent.change(screen.getByTestId("staff-totp"), {
    target: { value: "123456" },
  });
}

/**
 * The HTML spec's default button: the form's first submit button in tree order.
 * Implicit submission - Enter in a text control - activates it, so a form
 * without one cannot be submitted by Enter. jsdom implements neither implicit
 * submission nor this lookup, which is why the #572 AC-5 gate reads it
 * directly instead of dispatching a key.
 */
function defaultButtonOf(form: HTMLElement) {
  return form.querySelector<HTMLButtonElement>(
    'button[type="submit"], input[type="submit"]',
  );
}

// #566: the handoff's practice facts come from a doctor-profile read that is
// deliberately unmocked in this suite, so it reaches a real socket and takes a
// second to fail. #566 moved the handoff ahead of that read, so any test that
// has to wait for the destination to resolve stubs it out instead: the
// degrade-to-nulls path is already pinned, and the facts are not what those
// tests are about. Unstubbed by the afterEach.
function stubUnreachableProfileRead() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockRejectedValue(new TypeError("no network in unit tests")),
  );
}

// #566: the handoff now mounts on the OTP STAGE, so its being on screen no
// longer implies the destination has resolved - and the countdown and the CTA
// both stay held until it has. Wait for the released countdown before driving
// the handoff: a press before then is a legitimate no-op, not a defect.
async function waitForReleasedHandoff() {
  await waitFor(() => {
    expect(screen.getByRole("status").textContent).toMatch(/\d/);
  });
}

// #566: the destination-resolution seam, held open. After #562 `fetchPartnerMe`
// IS the route-state transport the production reader calls, and the reader runs
// it only after the session has been minted and saved - so signalling on entry
// names a deterministic instant: the flow is already terminal and nothing has
// resolved the destination yet. That instant is the gap the reported flash
// shipped through, because every other test in this file asserts the settled
// end state with waitFor and never looks at the surface in between.
//
// `reached` resolves on entry; `settle` closes the read. A test that never calls
// `settle` leaves the destination in flight for the whole test.
function holdDestinationRead() {
  let entered!: () => void;
  const reached = new Promise<void>((resolve) => {
    entered = resolve;
  });
  let close!: (view: PartnerMeView) => void;
  const pending = new Promise<PartnerMeView>((resolve) => {
    close = resolve;
  });
  mockFetchPartnerMe.mockImplementation(() => {
    entered();
    return pending;
  });
  return {
    reached,
    settle: (status: PartnerStatus) =>
      close({ partner_id: 7, partner_type: "doctor", round: 1, status }),
  };
}

// #566: the same partner transcript as completePartnerLogin, but on the real
// page, because the reported surface includes the heading the page owns. The
// destination is left to the caller (held, or answered by mockFetchPartnerMe).
async function completePartnerLoginOnPage() {
  vi.mocked(partnerLogin).mockResolvedValue(LOGIN_OK);
  vi.mocked(partnerVerify).mockResolvedValue({
    outcome: "verified",
    phone_e164: PHONE,
    identity_id: 7,
    attempts_left: null,
    lockout_remaining_seconds: null,
  });
  vi.mocked(issuePartnerSession).mockResolvedValue(SESSION);
  vi.mocked(fetchMe).mockResolvedValue({
    subject_id: "7",
    roles: ["partner"],
    phone: PHONE,
  });
  // The one landing the handoff exists for: an active doctor bound for the
  // doctor console. Any other resolved target routes straight on, with no
  // handoff, which is the other half of what these tests pin.
  mockPostLoginTarget.mockReturnValue("/doctor");
  render(<StaffLoginPage />);
  typePartnerPhone();
  fireEvent.click(screen.getByTestId("staff-submit"));
  await screen.findByTestId("partner-otp");
  typeCodeAndSubmit();
}

describe("StaffLoginForm - partner mode UI", () => {
  it("renders the phone step in partner mode - no email, password, or operator fields", () => {
    render(<StaffLoginForm />);
    expect(screen.getByTestId("partner-phone")).toBeInTheDocument();
    expect(screen.queryByTestId("staff-phone")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-totp")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-email")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-password")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /doctor|lab|chemist/i }),
    ).not.toBeInTheDocument();
  });

  it("shows no Phase-5 notice or forgot-password link on the partner card", () => {
    render(<StaffLoginForm />);
    expect(screen.queryByTestId("staff-phase5-notice")).not.toBeInTheDocument();
    expect(screen.queryByTestId("forgot-password")).not.toBeInTheDocument();
  });

  it("renders phone and TOTP fields in operator mode - no email, password, or partner fields", () => {
    render(<StaffLoginForm role="operator" />);
    expect(screen.getByTestId("staff-phone")).toBeInTheDocument();
    expect(screen.getByTestId("staff-totp")).toBeInTheDocument();
    expect(screen.queryByTestId("staff-email")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-password")).not.toBeInTheDocument();
    expect(screen.queryByTestId("partner-phone")).not.toBeInTheDocument();
  });

  it("never swaps fields while typing in partner mode", () => {
    render(<StaffLoginForm />);
    typePartnerPhone();
    // Still the phone step - typing never reshapes the field into the old
    // email/password layout or the operator phone+TOTP layout.
    expect(screen.getByTestId("partner-phone")).toBeInTheDocument();
    expect(screen.queryByTestId("staff-email")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-password")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-phone")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-totp")).not.toBeInTheDocument();
  });

  it("never swaps fields while typing in operator mode", () => {
    render(<StaffLoginForm role="operator" />);
    fireEvent.change(screen.getByTestId("staff-phone"), {
      target: { value: "9876543210" },
    });
    fireEvent.change(screen.getByTestId("staff-totp"), {
      target: { value: "123" },
    });
    expect(screen.queryByTestId("staff-email")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-password")).not.toBeInTheDocument();
    expect(screen.queryByTestId("partner-phone")).not.toBeInTheDocument();
  });

  it("validates phone on blur in operator mode", () => {
    render(<StaffLoginForm role="operator" />);
    fireEvent.change(screen.getByTestId("staff-phone"), {
      target: { value: "123" },
    });
    fireEvent.blur(screen.getByTestId("staff-phone"));
    expect(screen.getByTestId("staff-phone-error")).toHaveTextContent(
      t.phoneInvalid,
    );
  });

  it("validates TOTP code on blur in operator mode", () => {
    render(<StaffLoginForm role="operator" />);
    fireEvent.change(screen.getByTestId("staff-phone"), {
      target: { value: "9876543210" },
    });
    fireEvent.change(screen.getByTestId("staff-totp"), {
      target: { value: "123" },
    });
    fireEvent.blur(screen.getByTestId("staff-totp"));
    expect(screen.getByTestId("staff-totp-error")).toHaveTextContent(
      t.codeInvalid,
    );
  });

  it("summarizes invalid operator submits with a count", () => {
    render(<StaffLoginForm role="operator" />);
    fireEvent.click(screen.getByTestId("staff-submit"));
    expect(screen.getByTestId("staff-form-summary")).toBeInTheDocument();
  });
});

describe("StaffLoginForm - partner phone step", () => {
  it("rejects an empty or malformed phone client-side without calling the API", () => {
    render(<StaffLoginForm />);
    fireEvent.click(screen.getByTestId("staff-submit"));
    expect(screen.getByTestId("partner-error")).toHaveTextContent(
      t.phoneInvalid,
    );
    expect(vi.mocked(partnerLogin)).not.toHaveBeenCalled();
  });

  it("normalizes and requests a code for a valid phone", async () => {
    vi.mocked(partnerLogin).mockResolvedValue(LOGIN_OK);
    render(<StaffLoginForm />);
    typePartnerPhone();
    fireEvent.click(screen.getByTestId("staff-submit"));
    await screen.findByTestId("partner-otp");
    expect(vi.mocked(partnerLogin)).toHaveBeenCalledWith(PHONE);
  });

  it("shows the code step with expiry and normalized phone once a code is sent", async () => {
    await startPartnerOtpFlow();
    expect(screen.getByTestId("partner-otp")).toBeInTheDocument();
    expect(screen.getByTestId("partner-code-hint")).toHaveTextContent(PHONE);
    expect(screen.getByTestId("partner-code-expires")).toHaveTextContent(
      t.codeExpires,
    );
    expect(screen.getByTestId("partner-countdown")).toHaveTextContent("5:00");
    expect(screen.queryByTestId("partner-phone")).not.toBeInTheDocument();
  });

  it("goes back to the phone step and can restart with a new number", async () => {
    await startPartnerOtpFlow();
    fireEvent.click(screen.getByTestId("partner-edit-number"));
    expect(screen.getByTestId("partner-phone")).toBeInTheDocument();
    expect(screen.queryByTestId("partner-otp")).not.toBeInTheDocument();

    typePartnerPhone("9812345678");
    fireEvent.click(screen.getByTestId("staff-submit"));
    await waitFor(() => {
      expect(vi.mocked(partnerLogin)).toHaveBeenLastCalledWith("+919812345678");
    });
  });

  it("points unrecognized phones back to registration with no_account copy", async () => {
    vi.mocked(partnerLogin).mockResolvedValue({
      ...LOGIN_OK,
      outcome: "no_account",
      challenge_id: null,
    });
    render(<StaffLoginForm />);
    typePartnerPhone();
    fireEvent.click(screen.getByTestId("staff-submit"));
    expect(await screen.findByTestId("partner-error")).toHaveTextContent(
      t.noAccount,
    );
    expect(screen.queryByTestId("partner-otp")).not.toBeInTheDocument();
  });

  it("shows the cooldown copy when the backend is cooling the phone", async () => {
    vi.mocked(partnerLogin).mockResolvedValue({
      ...LOGIN_OK,
      outcome: "cooldown",
      challenge_id: null,
      cooldown_remaining_seconds: 45,
    });
    render(<StaffLoginForm />);
    typePartnerPhone();
    fireEvent.click(screen.getByTestId("staff-submit"));
    expect(await screen.findByTestId("partner-cooldown")).toHaveTextContent(
      t.resendIn(45),
    );
  });

  it("locks the phone input after too many failures", async () => {
    vi.mocked(partnerLogin).mockResolvedValue({
      ...LOGIN_OK,
      outcome: "locked",
      challenge_id: null,
      lockout_remaining_seconds: 600,
    });
    render(<StaffLoginForm />);
    typePartnerPhone();
    fireEvent.click(screen.getByTestId("staff-submit"));
    expect(await screen.findByTestId("partner-lockout")).toHaveTextContent(
      t.lockout(10),
    );
    expect(screen.getByTestId("partner-phone")).toBeDisabled();
  });

  it("shows the suspended notice for a suspended partner account", async () => {
    vi.mocked(partnerLogin).mockResolvedValue({
      ...LOGIN_OK,
      outcome: "suspended",
      challenge_id: null,
    });
    render(<StaffLoginForm />);
    typePartnerPhone();
    fireEvent.click(screen.getByTestId("staff-submit"));
    expect(await screen.findByTestId("partner-error")).toHaveTextContent(
      t.suspendedNotice,
    );
  });

  it("maps transport failures to calm copy without leaking codes", async () => {
    vi.mocked(partnerLogin).mockRejectedValue(
      new AuthApiError({
        code: "SMS_DELIVERY_FAILED",
        message: "sms down",
        trace_id: "t1",
        details: {},
      }),
    );
    render(<StaffLoginForm />);
    typePartnerPhone();
    fireEvent.click(screen.getByTestId("staff-submit"));
    const error = await screen.findByTestId("partner-error");
    expect(error).toHaveTextContent(t.smsFailed);
    expect(error).not.toHaveTextContent("SMS_DELIVERY_FAILED");
    expect(error).not.toHaveTextContent("t1");
  });

  it("shows network copy for connection failures", async () => {
    vi.mocked(partnerLogin).mockRejectedValue(new TypeError("Failed to fetch"));
    render(<StaffLoginForm />);
    typePartnerPhone();
    fireEvent.click(screen.getByTestId("staff-submit"));
    expect(await screen.findByTestId("partner-error")).toHaveTextContent(
      t.networkError,
    );
  });
});

describe("StaffLoginForm - partner resend", () => {
  it("disables resend during the cooldown window", async () => {
    await startPartnerOtpFlow();
    expect(screen.getByTestId("partner-resend-cooldown")).toHaveTextContent(
      t.resendIn(60),
    );
    expect(screen.getByTestId("partner-resend")).toBeDisabled();
    expect(vi.mocked(partnerLogin)).toHaveBeenCalledTimes(1);
  });

  it("shows cooldown copy when a resend hits the backend cooldown", async () => {
    await startPartnerOtpFlow({ ...LOGIN_OK, cooldown_remaining_seconds: 0 });
    vi.mocked(partnerLogin).mockResolvedValue({
      ...LOGIN_OK,
      outcome: "cooldown",
      challenge_id: null,
      cooldown_remaining_seconds: 30,
    });
    fireEvent.click(screen.getByTestId("partner-resend"));
    const error = await screen.findByTestId("partner-error");
    expect(error).toHaveTextContent(t.resendEarly(30));
    expect(screen.getByTestId("partner-resend-cooldown")).toHaveTextContent(
      t.resendIn(30),
    );
  });

  it("shows the latest-wins notice after a successful resend", async () => {
    await startPartnerOtpFlow({ ...LOGIN_OK, cooldown_remaining_seconds: 0 });
    vi.mocked(partnerLogin).mockResolvedValue(LOGIN_OK);
    fireEvent.click(screen.getByTestId("partner-resend"));
    expect(await screen.findByTestId("partner-notice")).toHaveTextContent(
      t.latestWins,
    );
    expect(vi.mocked(partnerLogin)).toHaveBeenCalledTimes(2);
    expect(vi.mocked(partnerLogin)).toHaveBeenLastCalledWith(PHONE);
  });
});

describe("StaffLoginForm - partner code step", () => {
  // #572: the step is built from the shared sign-in atoms the patient wizard
  // already renders, not from a second hand-built version of the same
  // interaction. These gates are split in two on purpose. The DOM assertions
  // prove the atoms render; the source gate proves the one-off utilities are
  // gone, because jsdom applies no stylesheet and
  // `expect(otp).not.toHaveClass("tracking-[0.5em]")` passes today while the
  // arbitrary letter-spacing is still in the file. Same reason
  // `design-tokens.test.ts` and the ring's CSS contract test read off disk.
  const here = (rel: string) => new URL(rel, import.meta.url);
  const source = readFileSync(here("./StaffLoginForm.tsx"), "utf8");
  // The slice runs from the partner branch's opener to the end of the file, so
  // it covers the phone step's own paragraph and input too. That is why the
  // list below holds only strings unique to the code step and the shared submit:
  // the operator TOTP step's two `opacity-80` help lines sit above the opener
  // and stay excluded, and the phone step's `mb-2 text-sm text-txt-sub` line
  // and its own input classes are inside the slice and left off the list,
  // because that step is not this ticket's.
  const PARTNER_BRANCH = 'partner.state.stage === "phone" ? (';
  const partnerBranchStart = source.indexOf(PARTNER_BRANCH);
  const partnerBranch = source.slice(partnerBranchStart);

  // Every one of these occurs only at a site this ticket replaces, which is
  // what makes "absent from the partner branch" a claim about the step.
  const ONE_OFF_UTILITIES = [
    "tracking-[0.5em]",
    "opacity-80",
    "mb-4 text-center",
    "text-lg font-semibold",
    "mb-4 flex items-center gap-3",
    "rounded-md border border-hairline px-3 py-1.5 text-sm",
    "text-sm underline",
    "mb-2 rounded-md border border-hairline bg-surface px-3 py-2 text-sm",
    "mt-1 w-full rounded-md bg-primary px-4 py-2 font-semibold text-on-accent",
    "mb-2 text-sm text-danger",
  ];

  it("has no arbitrary letter-spacing, bare percentage opacity, or one-off spacing left at the sites this ticket replaced (#572 AC-6)", () => {
    // Guards the slice itself: a renamed marker would make every assertion
    // below trivially true against a one-character string.
    expect(partnerBranchStart).toBeGreaterThan(0);
    for (const utility of ONE_OFF_UTILITIES) {
      expect(partnerBranch, utility).not.toContain(utility);
    }
    // Total, not regional: this file carried the letter-spacing exactly once.
    // The only other occurrence in the auth tree is the partner *registration*
    // wizard's, a different surface on a different ticket.
    expect(source).not.toContain("tracking-[0.5em]");
  });

  it("renders the shared six-box code input, with the hook on the hidden input (#572 AC-1)", async () => {
    await startPartnerOtpFlow();
    const otp = screen.getByTestId("partner-otp");
    expect(otp.tagName).toBe("INPUT");
    expect(otp).toHaveAttribute("maxlength", "6");
    expect(otp).toHaveClass(atomStyles.otpHiddenInput);
    // The boxes are the six siblings of the input, not six inputs of their own.
    const boxes = otp.parentElement?.querySelectorAll("span");
    expect(boxes).toHaveLength(6);
    for (const box of Array.from(boxes ?? [])) {
      expect(box).toHaveClass(atomStyles.otpBox);
    }
  });

  it("renders the shared countdown ring with the seconds inside it (#572 AC-1)", async () => {
    await startPartnerOtpFlow();
    const countdown = screen.getByTestId("partner-countdown");
    expect(countdown).toHaveTextContent("5:00");
    const ring = countdown.closest("div");
    expect(ring).toHaveClass(atomStyles.ring);
    expect(ring).toHaveAttribute("aria-hidden", "true");
    expect(ring?.querySelector("svg")).not.toBeNull();
  });

  it("lays the resend ghost and the edit-number link out as one considered row (#572 AC-2)", async () => {
    await startPartnerOtpFlow();
    const resend = screen.getByTestId("partner-resend");
    const edit = screen.getByTestId("partner-edit-number");
    expect(resend.tagName).toBe("BUTTON");
    expect(resend).toHaveClass(atomStyles.btnGhost);
    expect(edit.tagName).toBe("BUTTON");
    expect(edit).toHaveClass(atomStyles.editLink);
    expect(resend.parentElement).toBe(edit.parentElement);
    expect(resend.parentElement).toHaveClass(stepStyles.resendRow);
  });

  it("gives the demo-code read-back the notice treatment and keeps it a live region (#572 AC-3)", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    vi.mocked(fetchDemoOtp).mockResolvedValue("424242");
    await startPartnerOtpFlow();
    const banner = await screen.findByTestId("partner-demo-banner");
    // NoticeMessage, not the bordered neutral box that read as an error.
    expect(banner.tagName).toBe("P");
    expect(banner).toHaveClass(atomStyles.notice);
    // The code arrives asynchronously, so the announcement is the only thing
    // that reaches a screen reader. Every assertion on this banner is a text
    // match, so nothing else would notice its loss.
    expect(banner).toHaveAttribute("role", "status");
  });

  it("uses the shared error and notice treatments and the shared primary action (#572 AC-4)", async () => {
    vi.mocked(partnerVerify).mockResolvedValue(WRONG_CODE);
    await startPartnerOtpFlow({ ...LOGIN_OK, cooldown_remaining_seconds: 0 });
    typeCodeAndSubmit();
    const error = await screen.findByTestId("partner-error");
    expect(error.tagName).toBe("P");
    expect(error).toHaveClass(atomStyles.error);
    expect(error).toHaveAttribute("role", "alert");

    // The notice arm. Same atom as the banner, minus the alert: a latest-wins
    // confirmation is body copy, not a fault.
    vi.mocked(partnerLogin).mockResolvedValue(LOGIN_OK);
    fireEvent.click(screen.getByTestId("partner-resend"));
    const notice = await screen.findByTestId("partner-notice");
    expect(notice.tagName).toBe("P");
    expect(notice).toHaveClass(atomStyles.notice);
    expect(notice).not.toHaveAttribute("role", "alert");

    const submit = screen.getByTestId("staff-submit");
    expect(submit.tagName).toBe("BUTTON");
    expect(submit).toHaveClass(atomStyles.btnPrimary);
  });

  it("carries every state the step carried before the swap (#572 AC-7)", async () => {
    vi.mocked(partnerVerify).mockResolvedValue(WRONG_CODE);
    await startPartnerOtpFlow();
    // On the way up: expiry copy, countdown, the normalised number, the
    // resend cooldown - and the resend disabled for the same reason it always
    // was, which is the cooldown rather than the block.
    expect(screen.getByTestId("partner-code-expires")).toHaveTextContent(
      t.codeExpires,
    );
    expect(screen.getByTestId("partner-countdown")).toHaveTextContent("5:00");
    expect(screen.getByTestId("partner-code-hint")).toHaveTextContent(PHONE);
    // The hint's old `text-sm text-txt-sub` is the one string the source gate
    // cannot name, because the phone step's cooldown line still shares it, so
    // the treatment is pinned here instead.
    expect(screen.getByTestId("partner-code-hint")).toHaveClass(stepStyles.sub);
    expect(screen.getByTestId("partner-code-expires")).toHaveClass(
      stepStyles.sub,
    );
    expect(screen.getByTestId("partner-resend-cooldown")).toHaveTextContent(
      t.resendIn(60),
    );
    expect(screen.getByTestId("partner-resend")).toBeDisabled();
    // On the way back: the last error and the attempt budget restated against
    // the same six digits.
    typeCodeAndSubmit();
    expect(await screen.findByTestId("partner-error")).toHaveTextContent(
      t.wrongCode(4),
    );
    expect(screen.getByTestId("partner-attempts")).toHaveTextContent(
      t.attemptsLeft(4),
    );
  });

  it("locks the step out on both stages, and keeps the lockout an attempts band (#572 AC-7)", async () => {
    vi.mocked(partnerLogin).mockResolvedValue({
      ...LOGIN_OK,
      outcome: "locked",
      challenge_id: null,
      lockout_remaining_seconds: 600,
    });
    render(<StaffLoginForm />);
    typePartnerPhone();
    fireEvent.click(screen.getByTestId("staff-submit"));
    // The lockout line carries no stage guard: it is the one state both stages
    // render, and it shares the attempts treatment rather than a danger class.
    const lockout = await screen.findByTestId("partner-lockout");
    expect(lockout).toHaveTextContent(t.lockout(10));
    expect(lockout).toHaveClass(stepStyles.attempts);
    expect(screen.getByTestId("partner-phone")).toBeDisabled();
  });

  it("gives the code field a form whose default button carries the verify (#572 AC-5)", async () => {
    vi.mocked(partnerVerify).mockResolvedValue(WRONG_CODE);
    await startPartnerOtpFlow();
    const form = screen.getByTestId("staff-login-form");
    const input = screen.getByTestId("partner-otp");
    const submit = screen.getByTestId("staff-submit");
    // How Enter in a code field actually verifies, per the HTML spec: implicit
    // submission activates the form's *default button*, which is the first
    // submit button in tree order. There is no key handler anywhere in the
    // auth tree, so the control's `type` is the whole mechanism.
    //
    // jsdom implements neither implicit submission nor the default-button
    // lookup, and a `fireEvent.keyDown` here would be inert - it would pass on
    // a form with no submit button at all. So the gate is the two facts the
    // algorithm reads, and then the submission driven the way the brief's
    // done-verify allows (`fireEvent.submit`). The click path that depends on
    // the `type` is the negative gate's job, below.
    //
    // Precondition one: the field Enter lands in is in the form, and is one of
    // the input types the spec lists as implicit-submitting (`tel`).
    expect(form).toContainElement(input);
    expect(input).toHaveAttribute("type", "tel");
    // Precondition two: a *disabled* default button submits nothing.
    expect(submit).toBeEnabled();
    // Precondition three: this control is the default button. Drop the
    // `type="submit"` passthrough and the lookup finds nothing at all, which
    // is precisely why Enter silently stops verifying in a real browser while
    // every test in this suite stays green.
    expect(defaultButtonOf(form)).toBe(submit);
    // And the form does submit, through the handler Enter would have reached.
    typeCode();
    fireEvent.submit(form);
    await waitFor(() => expect(partnerVerify).toHaveBeenCalled());
    // And it was the code step's arm of the submit, not the phone step's.
    expect(await screen.findByTestId("partner-error")).toHaveTextContent(
      t.wrongCode(4),
    );
  });

  it("leaves the form with no default button when the passthrough is omitted (#572 AC-5)", () => {
    // The half that bites, and it is behavioural rather than an attribute
    // read. A `type="button"` atom inside a form gives the form no default
    // button, and clicking it does not submit. jsdom enforces exactly that,
    // which is why the two ids here are deliberately not the step's: this is
    // the atom's default in a form, not the partner step's own control, and
    // cloning the step's selectors would let it read as coverage the step does
    // not have. `shared.test.tsx` owns the default's own assertion; what is new
    // here is the consequence for a form.
    const submitted = vi.fn();
    render(
      <form
        onSubmit={(event) => {
          event.preventDefault();
          submitted();
        }}
        data-testid="probe-form"
      >
        <input aria-label="Verification code" inputMode="numeric" />
        <PrimaryButton testId="probe-submit">{t.getCode}</PrimaryButton>
      </form>,
    );
    const form = screen.getByTestId("probe-form");
    expect(defaultButtonOf(form)).toBeNull();
    fireEvent.click(screen.getByTestId("probe-submit"));
    expect(submitted).not.toHaveBeenCalled();
  });

  it("keeps the staff surface free of the patient wizard's chrome (#572 AC-9)", async () => {
    await startPartnerOtpFlow();
    // The layout classes this step adopts are the step's. The wizard's step
    // strip and registration value-props belong to the patient surface, and
    // this is the assertion that keeps them there.
    const page = readFileSync(
      here("../../../app/staff/login/page.tsx"),
      "utf8",
    );
    for (const file of [source, page]) {
      expect(file).not.toContain("valueProps");
      expect(file).not.toContain("stepNum");
      expect(file).not.toContain("stepLabel");
      expect(file).not.toContain("propIcon");
    }
    for (const prop of STRINGS.en.auth.valueProps) {
      expect(screen.queryByText(prop)).not.toBeInTheDocument();
    }
  });

  it("rejects a short code client-side without calling verify", async () => {
    await startPartnerOtpFlow();
    typeCodeAndSubmit("123");
    expect(screen.getByTestId("partner-error")).toHaveTextContent(t.shortCode);
    expect(vi.mocked(partnerVerify)).not.toHaveBeenCalled();
  });

  it("shows wrong-code copy with remaining attempts", async () => {
    await startPartnerOtpFlow();
    vi.mocked(partnerVerify).mockResolvedValue({
      outcome: "wrong_code",
      phone_e164: PHONE,
      identity_id: null,
      attempts_left: 4,
      lockout_remaining_seconds: null,
    });
    typeCodeAndSubmit();
    await waitFor(() => {
      expect(screen.getByTestId("partner-error")).toHaveTextContent(
        t.wrongCode(4),
      );
    });
    expect(screen.getByTestId("partner-attempts")).toHaveTextContent(
      t.attemptsLeft(4),
    );
    expect(vi.mocked(issuePartnerSession)).not.toHaveBeenCalled();
  });

  it("shows the expired-or-used copy for an expired code", async () => {
    await startPartnerOtpFlow();
    vi.mocked(partnerVerify).mockResolvedValue({
      outcome: "expired",
      phone_e164: PHONE,
      identity_id: null,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });
    typeCodeAndSubmit();
    await waitFor(() => {
      expect(screen.getByTestId("partner-error")).toHaveTextContent(
        t.expiredOrUsed,
      );
    });
  });

  it("shows the expired-or-used copy for a spent code", async () => {
    await startPartnerOtpFlow();
    vi.mocked(partnerVerify).mockResolvedValue({
      outcome: "spent",
      phone_e164: PHONE,
      identity_id: null,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });
    typeCodeAndSubmit();
    await waitFor(() => {
      expect(screen.getByTestId("partner-error")).toHaveTextContent(
        t.expiredOrUsed,
      );
    });
  });

  it("locks the code step when verification failures exhaust the phone", async () => {
    await startPartnerOtpFlow();
    vi.mocked(partnerVerify).mockResolvedValue({
      outcome: "locked",
      phone_e164: PHONE,
      identity_id: null,
      attempts_left: null,
      lockout_remaining_seconds: 600,
    });
    typeCodeAndSubmit();
    await waitFor(() => {
      expect(screen.getByTestId("partner-error")).toHaveTextContent(
        t.lockout(10),
      );
    });
    expect(screen.getByTestId("partner-otp")).toBeDisabled();
  });

  it("verifies the code, mints a partner session, and routes via postLoginTarget", async () => {
    stubUnreachableProfileRead();
    mockPostLoginTarget.mockReturnValue("/doctor");
    vi.mocked(partnerLogin).mockResolvedValue(LOGIN_OK);
    vi.mocked(partnerVerify).mockResolvedValue({
      outcome: "verified",
      phone_e164: PHONE,
      identity_id: 7,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });
    vi.mocked(issuePartnerSession).mockResolvedValue(SESSION);
    vi.mocked(fetchMe).mockResolvedValue({
      subject_id: "7",
      roles: ["partner"],
      phone: PHONE,
    });
    mockFetchPartnerMe.mockResolvedValue({
      partner_id: 7,
      partner_type: "doctor",
      round: 1,
      status: "Active",
    });

    render(<StaffLoginForm />);
    typePartnerPhone();
    fireEvent.click(screen.getByTestId("staff-submit"));
    await screen.findByTestId("partner-otp");
    typeCodeAndSubmit();

    await waitFor(() => {
      expect(vi.mocked(partnerVerify)).toHaveBeenCalledWith(PHONE, "123456");
      expect(vi.mocked(issuePartnerSession)).toHaveBeenCalledWith(PHONE);
      expect(vi.mocked(fetchMe)).toHaveBeenCalledWith(SESSION.jwt);
      expect(mockSaveSession).toHaveBeenCalledWith(SESSION, PHONE);
      expect(mockFetchPartnerMe).toHaveBeenCalled();
      expect(mockPostLoginTarget).toHaveBeenCalledWith({
        surface: "staff",
        roles: ["partner"],
        partnerState: undefined,
        partnerType: "doctor",
      });
      // #537 AC-1/AC-3: an ACTIVE doctor lands on the shared done screen and
      // moves with the framework router - never a hard page reload.
      expect(mockLocationReplace).not.toHaveBeenCalled();
      expect(screen.getByRole("heading", { name: "Identity verified" }));
      expect(screen.getByRole("status")).toHaveTextContent(
        "Opening your dashboard",
      );
      expect(
        screen.getByRole("button", { name: "Go to Dashboard" }),
      ).toBeInTheDocument();
    });

    // AC-1 CTA: "Go to Dashboard" routes to the resolved target directly.
    // #566: it can only do that once the destination is in hand, so wait for
    // the released countdown rather than assuming the landing already settled.
    await waitForReleasedHandoff();
    fireEvent.click(screen.getByRole("button", { name: "Go to Dashboard" }));
    await waitFor(() => {
      expect(mockRouterReplace).toHaveBeenCalledWith("/doctor");
    });

    await waitFor(() => {
      expect(authState.resumeSession).toHaveBeenCalled();
    });

    // The patient lifecycle is never touched for a partner sign-in.
    expect(vi.mocked(issueSession)).not.toHaveBeenCalled();
    expect(vi.mocked(registerPhone)).not.toHaveBeenCalled();
    expect(vi.mocked(verifyOtp)).not.toHaveBeenCalled();
  });

  // #562: the shared partner-login transcript. `status: undefined` installs NO
  // partner-status answer, which is how the ordering probe below reads the bare
  // seam; `partnerType` is a parameter so a test states the type it means rather
  // than inheriting "doctor".
  async function completePartnerLogin(
    status: PartnerStatus | undefined,
    returnTarget?: string | null,
    partnerType: PartnerType = "doctor",
  ) {
    vi.mocked(partnerLogin).mockResolvedValue(LOGIN_OK);
    vi.mocked(partnerVerify).mockResolvedValue({
      outcome: "verified",
      phone_e164: PHONE,
      identity_id: 7,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });
    vi.mocked(issuePartnerSession).mockResolvedValue(SESSION);
    vi.mocked(fetchMe).mockResolvedValue({
      subject_id: "7",
      roles: ["partner"],
      phone: PHONE,
    });
    if (status !== undefined) {
      mockFetchPartnerMe.mockResolvedValue({
        partner_id: 7,
        partner_type: partnerType,
        round: 1,
        status,
      });
    }
    render(<StaffLoginForm returnTarget={returnTarget} />);
    typePartnerPhone();
    fireEvent.click(screen.getByTestId("staff-submit"));
    await screen.findByTestId("partner-otp");
    typeCodeAndSubmit();
  }

  it.each([
    ["Registered", "pending", "/partner/status/pending"],
    ["Under Verification", "pending", "/partner/status/pending"],
    ["Rejected", "rejected", "/partner/status/rejected"],
  ] as const)(
    "lands an already-logged-in %s partner on %s via postLoginTarget",
    async (status, state, expected) => {
      mockPostLoginTarget.mockReturnValue(expected);
      await completePartnerLogin(status);

      await waitFor(() => {
        expect(mockFetchPartnerMe).toHaveBeenCalled();
        expect(mockPostLoginTarget).toHaveBeenCalledWith({
          surface: "staff",
          roles: ["partner"],
          partnerState: state,
          partnerType: "doctor",
        });
        expect(mockLocationReplace).toHaveBeenCalledWith(expected);
      });

      // #566 AC-6: no console destination is ever engaged for a partner who is
      // not an active doctor. `landing` is never set on this path, so the
      // handoff's countdown and its CTA both stay no-ops - asserted here rather
      // than inferred from the routing call, because a mocked location.replace
      // never tears the tree down the way a real hard navigation would. What
      // keeps the handoff from being the active-partner-only moment is the
      // routing, not a second render condition: the ticket freezes these three
      // exit branches, and the handoff is keyed to the OTP stage alone.
      expect(screen.queryByTestId("staff-submit")).not.toBeInTheDocument();
      expect(screen.queryByTestId("partner-otp")).not.toBeInTheDocument();
      // Held, because there is nowhere to count down to: the digit-free opening
      // line, and no navigation to a console path.
      expect(screen.getByRole("status").textContent).not.toMatch(/\d/);
      expect(mockRouterReplace).not.toHaveBeenCalled();
    },
  );

  it("derives no partnerState for an active doctor partner and lands via the doctor role rule", async () => {
    stubUnreachableProfileRead();
    mockPostLoginTarget.mockReturnValue("/doctor");
    await completePartnerLogin("Active");

    await waitFor(() => {
      expect(mockFetchPartnerMe).toHaveBeenCalled();
      expect(mockPostLoginTarget).toHaveBeenCalledWith({
        surface: "staff",
        roles: ["partner"],
        partnerState: undefined,
        partnerType: "doctor",
      });
      // #537 AC-1/AC-3: an ACTIVE doctor lands on the shared done screen and
      // moves with the framework router - never a hard page reload.
      expect(mockLocationReplace).not.toHaveBeenCalled();
      expect(screen.getByRole("heading", { name: "Identity verified" }));
      expect(screen.getByRole("status")).toHaveTextContent(
        "Opening your dashboard",
      );
    });

    // #562: the countdown firing at zero is DoneScreen's own pinned contract
    // (DoneScreen.test.tsx, "counts the visible seconds down and fires the host
    // routine at zero (#551)"), so drive the handoff with the CTA rather than
    // waiting out a 5s timer here. #566: the CTA holds until the destination
    // is in hand, so wait for that first.
    await waitForReleasedHandoff();
    fireEvent.click(screen.getByRole("button", { name: "Go to Dashboard" }));

    await waitFor(() => {
      expect(authState.resumeSession).toHaveBeenCalled();
      expect(mockRouterReplace).toHaveBeenCalledWith("/doctor");
    });
  });

  it("threads the arrival ?return= target through the landing for an active partner (F014-T09b)", async () => {
    mockPostLoginTarget.mockReturnValue("/partner/orders/42");
    await completePartnerLogin("Active", "/partner/orders/42");

    await waitFor(() => {
      expect(mockPostLoginTarget).toHaveBeenCalledWith(
        expect.objectContaining({
          surface: "staff",
          roles: ["partner"],
          partnerState: undefined,
          partnerType: "doctor",
          returnTarget: "/partner/orders/42",
        }),
      );
      // #537: the active path routes with the framework router, not a hard
      // reload, so mockLocationReplace must stay untouched.
      expect(mockLocationReplace).not.toHaveBeenCalled();
    });

    await waitFor(() => {
      expect(authState.resumeSession).toHaveBeenCalled();
      expect(mockRouterReplace).toHaveBeenCalledWith("/partner/orders/42");
    });
  });

  it.each([
    ["Under Verification", "pending", "/partner/status/pending"],
    ["Rejected", "rejected", "/partner/status/rejected"],
  ] as const)(
    "passes the return target even when the %s partner state overrides it downstream (F014-T09b)",
    async (status, state, expected) => {
      mockPostLoginTarget.mockReturnValue(expected);
      await completePartnerLogin(status, "/partner/orders/42");

      await waitFor(() => {
        expect(mockPostLoginTarget).toHaveBeenCalledWith(
          expect.objectContaining({
            surface: "staff",
            roles: ["partner"],
            partnerState: state,
            partnerType: "doctor",
            returnTarget: "/partner/orders/42",
          }),
        );
        expect(mockLocationReplace).toHaveBeenCalledWith(expected);
      });
    },
  );

  it("falls back to role-based routing when the partner status read fails", async () => {
    mockPostLoginTarget.mockReturnValue("/partner");
    vi.mocked(partnerLogin).mockResolvedValue(LOGIN_OK);
    vi.mocked(partnerVerify).mockResolvedValue({
      outcome: "verified",
      phone_e164: PHONE,
      identity_id: 7,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });
    vi.mocked(issuePartnerSession).mockResolvedValue(SESSION);
    vi.mocked(fetchMe).mockResolvedValue({
      subject_id: "7",
      roles: ["partner"],
      phone: PHONE,
    });
    mockFetchPartnerMe.mockRejectedValue(
      new ApiError({
        code: "NETWORK_ERROR",
        message: "down",
        trace_id: "tr-partner-me",
        details: {},
      }),
    );

    render(<StaffLoginForm />);
    typePartnerPhone();
    fireEvent.click(screen.getByTestId("staff-submit"));
    await screen.findByTestId("partner-otp");
    typeCodeAndSubmit();

    await waitFor(() => {
      expect(mockPostLoginTarget).toHaveBeenCalledWith({
        surface: "staff",
        roles: ["partner"],
        partnerState: undefined,
        partnerType: undefined,
      });
      expect(mockLocationReplace).toHaveBeenCalledWith("/partner");
    });
  });

  it("does not read partner status for a non-partner session", async () => {
    mockPostLoginTarget.mockReturnValue("/operator/home");
    vi.mocked(partnerLogin).mockResolvedValue(LOGIN_OK);
    vi.mocked(partnerVerify).mockResolvedValue({
      outcome: "verified",
      phone_e164: PHONE,
      identity_id: 7,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });
    vi.mocked(issuePartnerSession).mockResolvedValue(SESSION);
    vi.mocked(fetchMe).mockResolvedValue({
      subject_id: "7",
      roles: ["operator"],
      phone: PHONE,
    });

    render(<StaffLoginForm />);
    typePartnerPhone();
    fireEvent.click(screen.getByTestId("staff-submit"));
    await screen.findByTestId("partner-otp");
    typeCodeAndSubmit();

    await waitFor(() => {
      expect(mockFetchPartnerMe).not.toHaveBeenCalled();
      expect(mockPostLoginTarget).toHaveBeenCalledWith({
        surface: "staff",
        roles: ["operator"],
        partnerState: undefined,
        partnerType: undefined,
      });
    });
  });

  // #562 AC-4: the two tests below are a deliberate ordering probe. The first
  // installs a persistent (non-Once) partner-status answer; the second installs
  // none and reads the bare seam, so it can only be green if that answer was
  // wiped between the two. Revert the afterEach to vi.clearAllMocks() and the
  // second inherits "rejected"/"lab" and fails - which is exactly how the ten
  // original failures read. Each test states its own answer or its own lack of
  // one, so the pair carries the same verdict in either order and standalone.
  it("routes by a partner-status answer installed for this test only (#562)", async () => {
    mockPostLoginTarget.mockReturnValue("/partner/status/rejected");
    await completePartnerLogin("Rejected", undefined, "lab");

    await waitFor(() => {
      expect(mockPostLoginTarget).toHaveBeenCalledWith({
        surface: "staff",
        roles: ["partner"],
        partnerState: "rejected",
        partnerType: "lab",
      });
    });
  });

  it("routes by role when no partner-status answer is installed (#562)", async () => {
    mockPostLoginTarget.mockReturnValue("/partner");
    // status: undefined installs NO answer, so the seam is bare: the read
    // returns no usable status, the reader's defensive catch takes over, and
    // routing falls back to the role rule. Anything left over from the test
    // above would arrive here as a real status and fail this assertion - which
    // is the whole point. (The realistic unreadable-read path is pinned
    // separately, by the rejected-read test above.)
    await completePartnerLogin(undefined);

    await waitFor(() => {
      // The real reader ran, so this is a live seam assertion (AC-3), not a
      // mock production never reaches.
      expect(mockFetchPartnerMe).toHaveBeenCalled();
      expect(mockPostLoginTarget).toHaveBeenCalledWith({
        surface: "staff",
        roles: ["partner"],
        partnerState: undefined,
        partnerType: undefined,
      });
    });
  });

  it("shows the envelope notice when the post-login landing fails", async () => {
    vi.mocked(partnerLogin).mockResolvedValue(LOGIN_OK);
    vi.mocked(partnerVerify).mockResolvedValue({
      outcome: "verified",
      phone_e164: PHONE,
      identity_id: 7,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });
    vi.mocked(issuePartnerSession).mockResolvedValue(SESSION);
    vi.mocked(fetchMe).mockRejectedValue(
      new ApiError({
        code: "NETWORK_ERROR",
        message: "down",
        trace_id: "tr-landing",
        details: {},
      }),
    );

    render(<StaffLoginForm />);
    typePartnerPhone();
    fireEvent.click(screen.getByTestId("staff-submit"));
    await screen.findByTestId("partner-otp");
    typeCodeAndSubmit();

    await waitFor(() => {
      const error = screen.getByTestId("staff-login-error");
      expect(error).toHaveTextContent("tr-landing");
    });
    // #566 AC-4: a destination resolution that fails leaves the handoff up
    // with the envelope explanation beside it. Before the fix the done branch
    // returned null while `landing` was unset, so the same failure rendered a
    // blank card under a live submit button - and the test above, which only
    // ever read the notice, could not tell the two apart.
    expect(
      screen.getByRole("heading", { name: "Identity verified" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("staff-submit")).not.toBeInTheDocument();
    expect(screen.queryByTestId("partner-otp")).not.toBeInTheDocument();
    expect(mockLocationReplace).not.toHaveBeenCalled();
  });
});

// #566: the verified handoff renders on the OTP STAGE, not on the resolved
// destination. Every test above waits for the destination and then reads the
// settled end state, so nothing in the suite ever looked at the window between
// "the code was accepted" and "the destination resolved" - a window exactly as
// long as the three post-login round-trips, during which the submit button was
// live and its label had fallen through to the phone step's "Get verification
// code". These tests assert that window directly.
describe("StaffLoginForm - verified handoff on the OTP stage (#566)", () => {
  it("mounts the handoff synchronously at the held instant, with no stale sign-in surface (#566 AC-1/AC-2/AC-8)", async () => {
    const destination = holdDestinationRead();
    await completePartnerLoginOnPage();

    // The whole point: the instant. The destination read has been entered and
    // is still held, so the flow is terminal and nothing has resolved. Reaching
    // it is a single await on the read itself plus one flush - no waitFor, no
    // findBy, no polling, and no clock to wait on.
    await destination.reached;
    await act(async () => {});

    // The handoff is up, and it says it is still waiting: the digit-free
    // opening line, not a countdown that has nowhere to count down to.
    expect(
      screen.getByRole("heading", { level: 1, name: "Identity verified" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Opening your dashboard",
    );
    expect(screen.getByRole("status").textContent).not.toMatch(/\d/);
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      String(DONE_SCREEN_COUNTDOWN_SECONDS),
    );

    // The reported flash, item by item: no code input, no submit control, and
    // no page heading still telling a verified partner they are signing in.
    expect(screen.queryByTestId("partner-otp")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-submit")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: t.heading }),
    ).not.toBeInTheDocument();
    // Counted, not just absent-by-name: DoneScreen brings its own h1, so a
    // leftover page heading would leave two on the document.
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("holds the countdown until the destination is in hand, then fires it exactly once (#566 AC-3)", async () => {
    // Fake the tick only. DoneScreen counts down on setInterval; faking the
    // rest of the clock would stall the real doctor-profile read that resolves
    // the destination, and this test needs that read to actually land.
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval"] });
    stubUnreachableProfileRead();
    const destination = holdDestinationRead();
    await completePartnerLoginOnPage();
    await destination.reached;
    await act(async () => {});

    // The negative half, and the half that matters: the resume seam has long
    // settled but the destination has not, so nothing may move. Wiring the
    // countdown to the resume seam alone passes every other test here and fails
    // this one - the countdown would run for seconds with no target to reach.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DONE_SCREEN_COUNTDOWN_SECONDS * 2000);
    });
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      String(DONE_SCREEN_COUNTDOWN_SECONDS),
    );
    expect(screen.getByRole("status").textContent).not.toMatch(/\d/);
    expect(mockRouterReplace).not.toHaveBeenCalled();
    // The active path is never a hard reload: a released countdown with no
    // destination must not fall through to one either.
    expect(mockLocationReplace).not.toHaveBeenCalled();
    // Started on the session, not on the resolved destination, and still one
    // call: the handoff is on screen and the resume seam has already run.
    expect(authState.resumeSession).toHaveBeenCalledTimes(1);

    // Both seams settled: the countdown is released, and it navigates once.
    await act(async () => {
      destination.settle("Active");
    });
    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toMatch(/\d/);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(DONE_SCREEN_COUNTDOWN_SECONDS * 1000);
    });
    expect(mockRouterReplace).toHaveBeenCalledTimes(1);
    expect(mockRouterReplace).toHaveBeenCalledWith("/doctor");
  });

  it("names every step's submit label, the terminal one included (#566 AC-5)", async () => {
    // The terminal arm, which no DOM assertion can reach: the control is
    // rendered out on the terminal step, so the mapping is asserted where it
    // lives. This is the reported defect's label - the phone step's copy under
    // an already-verified partner.
    const step = {
      isMfaStep: false,
      isOperatorMode: false,
      stage: "done",
    } as const;
    expect(staffSubmitLabel(t, step)).toBe(t.verifiedSubmit);
    expect(staffSubmitLabel(t, step)).not.toBe(t.getCode);
    // Both locales carry the terminal copy.
    const hi = STRINGS.hi.staffAuth.login;
    expect(staffSubmitLabel(hi, step)).toBe(hi.verifiedSubmit);
    expect(hi.verifiedSubmit).not.toBe(hi.getCode);
    // Every other stage keeps its own label: the arms the reordering trap
    // would silently change, pinned by value rather than by position.
    expect(staffSubmitLabel(t, { ...step, stage: "phone" })).toBe(t.getCode);
    expect(staffSubmitLabel(t, { ...step, stage: "otp" })).toBe(t.mfaSubmit);
    expect(staffSubmitLabel(t, { ...step, isOperatorMode: true })).toBe(
      t.signIn,
    );
    expect(staffSubmitLabel(t, { ...step, isMfaStep: true })).toBe(t.mfaSubmit);
  });

  it("renders each step's own submit label through the component (#566 AC-5)", async () => {
    // Phone step: the request-the-code label.
    render(<StaffLoginForm />);
    expect(screen.getByTestId("staff-submit")).toHaveTextContent(t.getCode);
    cleanup();

    // OTP step: the verify-the-code label. The operator and MFA arms are the
    // ones a "reorder the ternary until it looks right" fix silently changes,
    // so all three are pinned here through the component too.
    await startPartnerOtpFlow();
    expect(screen.getByTestId("staff-submit")).toHaveTextContent(t.mfaSubmit);
    cleanup();

    render(<StaffLoginForm role="operator" />);
    fillPhoneAndTotp();
    expect(screen.getByTestId("staff-submit")).toHaveTextContent(t.signIn);
    cleanup();

    mockOperatorLogin.mockRejectedValue(
      new ApiError({
        code: "SESSION_MFA_REQUIRED",
        message: "mfa required",
        trace_id: "tr-label",
        details: {},
      }),
    );
    render(<StaffLoginForm role="operator" />);
    fillPhoneAndTotp();
    fireEvent.click(screen.getByTestId("staff-submit"));
    await screen.findByTestId("mfa-input");
    expect(screen.getByTestId("staff-submit")).toHaveTextContent(t.mfaSubmit);
  });
});

describe("StaffLoginForm - partner demo OTP banner", () => {
  it("shows the read-back banner when NEXT_PUBLIC_DEMO_MODE=true", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    vi.mocked(fetchDemoOtp).mockResolvedValue("424242");
    await startPartnerOtpFlow();
    expect(await screen.findByTestId("partner-demo-banner")).toHaveTextContent(
      t.demoOtp("424242"),
    );
    expect(vi.mocked(fetchDemoOtp)).toHaveBeenCalledWith(PHONE);
  });

  it("re-fetches and shows the new code after a successful resend", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    vi.mocked(fetchDemoOtp).mockResolvedValue("424242");
    await startPartnerOtpFlow({ ...LOGIN_OK, cooldown_remaining_seconds: 0 });
    expect(await screen.findByTestId("partner-demo-banner")).toHaveTextContent(
      t.demoOtp("424242"),
    );

    vi.mocked(fetchDemoOtp).mockResolvedValue("999999");
    vi.mocked(partnerLogin).mockResolvedValue(LOGIN_OK);
    fireEvent.click(screen.getByTestId("partner-resend"));

    await waitFor(() => {
      expect(screen.getByTestId("partner-demo-banner")).toHaveTextContent(
        t.demoOtp("999999"),
      );
    });
    expect(vi.mocked(fetchDemoOtp)).toHaveBeenCalledTimes(2);
  });

  it("shows no banner and makes no read-back call without the flag", async () => {
    await startPartnerOtpFlow();
    expect(screen.queryByTestId("partner-demo-banner")).not.toBeInTheDocument();
    expect(vi.mocked(fetchDemoOtp)).not.toHaveBeenCalled();
  });
});

describe("Operator login flow", () => {
  it("calls operatorLogin with phone and 6-digit TOTP code on submit", async () => {
    mockOperatorLogin.mockResolvedValue({
      jwt: "abc",
      jti: "j1",
      scope: "operator",
      identity_id: 5,
      expires_in_seconds: 3600,
      refresh_token: "rt",
    });
    vi.mocked(fetchMe).mockResolvedValue({
      subject_id: "5",
      phone: "+919876543210",
      roles: ["operator"],
    });

    render(<StaffLoginForm role="operator" />);
    fillPhoneAndTotp();
    fireEvent.click(screen.getByTestId("staff-submit"));

    await waitFor(() => {
      expect(mockOperatorLogin).toHaveBeenCalledWith({
        phone: "9876543210",
        code: "123456",
      });
    });
  });

  it("saves session and routes on successful login", async () => {
    const session = {
      jwt: "abc",
      jti: "j1",
      scope: "operator",
      identity_id: 5,
      expires_in_seconds: 3600,
      refresh_token: "rt",
    };
    mockOperatorLogin.mockResolvedValue(session);
    vi.mocked(fetchMe).mockResolvedValue({
      subject_id: "5",
      phone: "+919876543210",
      roles: ["operator"],
    });

    render(<StaffLoginForm role="operator" />);
    fillPhoneAndTotp();
    fireEvent.click(screen.getByTestId("staff-submit"));

    await waitFor(() => {
      expect(mockSaveSession).toHaveBeenCalledWith(session, "+919876543210");
      expect(mockPostLoginTarget).toHaveBeenCalledWith({
        surface: "staff",
        roles: ["operator"],
        partnerState: undefined,
        partnerType: undefined,
      });
      expect(mockLocationReplace).toHaveBeenCalledWith("/operator/home");
    });
  });

  it("rejects a non-6-digit TOTP code without calling the API", async () => {
    render(<StaffLoginForm role="operator" />);
    fireEvent.change(screen.getByTestId("staff-phone"), {
      target: { value: "9876543210" },
    });
    fireEvent.change(screen.getByTestId("staff-totp"), {
      target: { value: "123" },
    });
    fireEvent.click(screen.getByTestId("staff-submit"));

    expect(screen.getByTestId("staff-totp-error")).toHaveTextContent(
      t.codeInvalid,
    );
    expect(mockOperatorLogin).not.toHaveBeenCalled();
  });

  it("rejects a TOTP code with letters without calling the API", async () => {
    render(<StaffLoginForm role="operator" />);
    fireEvent.change(screen.getByTestId("staff-phone"), {
      target: { value: "9876543210" },
    });
    fireEvent.change(screen.getByTestId("staff-totp"), {
      target: { value: "abcdef" },
    });
    fireEvent.click(screen.getByTestId("staff-submit"));

    expect(screen.getByTestId("staff-totp-error")).toHaveTextContent(
      t.codeInvalid,
    );
    expect(mockOperatorLogin).not.toHaveBeenCalled();
  });

  it("surfaces SESSION_MFA_REQUIRED as TOTP re-verification step", async () => {
    mockOperatorLogin.mockRejectedValue(
      new ApiError({
        code: "SESSION_MFA_REQUIRED",
        message: "mfa required",
        trace_id: "trace-123",
        details: {},
      }),
    );
    render(<StaffLoginForm role="operator" />);
    fillPhoneAndTotp();
    fireEvent.click(screen.getByTestId("staff-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("mfa-input")).toBeInTheDocument();
    });
    // Masked phone displayed, not raw PII.
    expect(screen.getByTestId("mfa-phone-display")).toHaveTextContent(/X/);
    expect(screen.queryByTestId("staff-phone")).not.toBeInTheDocument();
  });

  it("submits TOTP code and creates session on MFA success", async () => {
    // First call: TOTP triggers MFA (SESSION_MFA_REQUIRED)
    mockOperatorLogin
      .mockRejectedValueOnce(
        new ApiError({
          code: "SESSION_MFA_REQUIRED",
          message: "mfa required",
          trace_id: "t",
          details: {},
        }),
      )
      .mockResolvedValueOnce({
        jwt: "xyz",
        jti: "j2",
        scope: "operator",
        identity_id: 5,
        expires_in_seconds: 3600,
        refresh_token: "rt2",
      });
    vi.mocked(fetchMe).mockResolvedValue({
      subject_id: "5",
      phone: "+919876543210",
      roles: ["operator"],
    });

    render(<StaffLoginForm role="operator" />);
    fillPhoneAndTotp();
    fireEvent.click(screen.getByTestId("staff-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("mfa-input")).toBeInTheDocument();
    });

    // Enter TOTP and submit
    fireEvent.change(screen.getByTestId("mfa-input"), {
      target: { value: "654321" },
    });
    fireEvent.click(screen.getByTestId("staff-submit"));

    await waitFor(() => {
      expect(mockOperatorLogin).toHaveBeenLastCalledWith({
        phone: "9876543210",
        code: "654321",
      });
      expect(mockLocationReplace).toHaveBeenCalledWith("/operator/home");
    });
  });

  it("rejects a short TOTP code in MFA re-verification without calling the API", async () => {
    mockOperatorLogin.mockRejectedValue(
      new ApiError({
        code: "SESSION_MFA_REQUIRED",
        message: "mfa required",
        trace_id: "t",
        details: {},
      }),
    );

    render(<StaffLoginForm role="operator" />);
    fillPhoneAndTotp();
    fireEvent.click(screen.getByTestId("staff-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("mfa-input")).toBeInTheDocument();
    });

    // Enter a code too short to verify.
    fireEvent.change(screen.getByTestId("mfa-input"), {
      target: { value: "123" },
    });
    fireEvent.click(screen.getByTestId("staff-submit"));

    expect(screen.getByTestId("mfa-code-error")).toHaveTextContent(
      t.codeInvalid,
    );
    // The short code never goes out to the API.
    expect(mockOperatorLogin).toHaveBeenCalledTimes(1);
  });

  it("shows envelope error with traceId for failed login", async () => {
    mockOperatorLogin.mockRejectedValue(
      new ApiError({
        code: "INVALID_CREDENTIALS",
        message: "bad creds",
        trace_id: "trace-456",
        details: {},
      }),
    );

    render(<StaffLoginForm role="operator" />);
    fillPhoneAndTotp();
    fireEvent.click(screen.getByTestId("staff-submit"));

    await waitFor(() => {
      const error = screen.getByTestId("staff-login-error");
      // INVALID_CREDENTIALS maps to localized copy - the raw code is never shown.
      expect(error).toHaveTextContent(t.invalidCredentials);
      expect(error).not.toHaveTextContent("INVALID_CREDENTIALS");
      // The envelope's trace id is still surfaced alongside the copy.
      expect(error).toHaveTextContent("trace-456");
    });
  });

  it("shows INVALID_OPERATOR_CODE error on first submission without transitioning to MFA", async () => {
    mockOperatorLogin.mockRejectedValue(
      new ApiError({
        code: "INVALID_OPERATOR_CODE",
        message: "invalid code",
        trace_id: "trace-totp",
        details: {},
      }),
    );

    render(<StaffLoginForm role="operator" />);
    fillPhoneAndTotp();
    fireEvent.click(screen.getByTestId("staff-submit"));

    await waitFor(() => {
      const error = screen.getByTestId("staff-login-error");
      expect(error).toHaveTextContent(t.invalidOperatorCode);
    });
    // Should stay on phone+code step, not transition to MFA.
    expect(screen.getByTestId("staff-phone")).toBeInTheDocument();
    expect(screen.queryByTestId("mfa-input")).not.toBeInTheDocument();
  });

  it("shows INVALID_OPERATOR_CODE error on MFA re-entry", async () => {
    mockOperatorLogin
      .mockRejectedValueOnce(
        new ApiError({
          code: "SESSION_MFA_REQUIRED",
          message: "mfa required",
          trace_id: "t",
          details: {},
        }),
      )
      .mockRejectedValueOnce(
        new ApiError({
          code: "INVALID_OPERATOR_CODE",
          message: "invalid code",
          trace_id: "trace-mfa",
          details: {},
        }),
      );

    render(<StaffLoginForm role="operator" />);
    fillPhoneAndTotp();
    fireEvent.click(screen.getByTestId("staff-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("mfa-input")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("mfa-input"), {
      target: { value: "000000" },
    });
    fireEvent.click(screen.getByTestId("staff-submit"));

    await waitFor(() => {
      const error = screen.getByTestId("staff-login-error");
      expect(error).toHaveTextContent(t.invalidOperatorCode);
    });
  });

  it("disables submit button while loading", async () => {
    let resolveLogin: (v: unknown) => void;
    mockOperatorLogin.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveLogin = resolve;
        }),
    );

    render(<StaffLoginForm role="operator" />);
    fillPhoneAndTotp();
    fireEvent.click(screen.getByTestId("staff-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("staff-submit")).toBeDisabled();
    });

    resolveLogin!({
      jwt: "abc",
      jti: "j1",
      scope: "operator",
      identity_id: 5,
      expires_in_seconds: 3600,
      refresh_token: "rt",
    });
  });

  it("does not call operatorLogin in partner mode", async () => {
    vi.mocked(partnerLogin).mockResolvedValue(LOGIN_OK);
    render(<StaffLoginForm />);
    typePartnerPhone();
    fireEvent.click(screen.getByTestId("staff-submit"));
    await screen.findByTestId("partner-otp");

    expect(mockOperatorLogin).not.toHaveBeenCalled();
    expect(vi.mocked(partnerLogin)).toHaveBeenCalledTimes(1);
  });
});
