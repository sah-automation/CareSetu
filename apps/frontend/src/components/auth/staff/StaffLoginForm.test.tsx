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
import * as axe from "axe-core";

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
import type { DoctorProfileView } from "@/lib/doctor/api";
import { HANDOFF_MINIMUM_DWELL_MS } from "@/lib/auth/useHandoffNavigation";
import type {
  PartnerMeView,
  PartnerStatus,
  PartnerType,
} from "@/lib/partner/api";

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
  // #566: the handoff tests below and in the next block fake the handoff's own
  // clocks; without this the fake interval would outlive the suite it was
  // installed for.
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

// The private doctor projection the handoff's fact rows are built from. The
// full shape is spelled out because the client guards it, and only two fields
// are ever interesting to a test - so `profile.practice_name` and
// `profile.specialty` are the knobs, by way of the overrides.
function doctorProfile(
  overrides: Partial<DoctorProfileView> = {},
): DoctorProfileView {
  return {
    partner_id: 7,
    photo_ref: null,
    practice_name: "Kumar Clinic",
    specialty: "General physician",
    verified: true,
    practice_address: "12 MG Road",
    practice_latitude: 12.9716,
    practice_longitude: 77.5946,
    area: "Indiranagar",
    languages: ["English", "Kannada"],
    experience_years: 9,
    about: null,
    consultation_fee: 50000,
    availability: null,
    credentials: [],
    notification_preferences: {},
    ...overrides,
  };
}

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
  // The container comes back so a caller can scope a query or a scan to the
  // step. Nothing here changes for the callers that ignore it.
  const { container } = render(<StaffLoginForm />);
  typePartnerPhone();
  fireEvent.click(screen.getByTestId("staff-submit"));
  await screen.findByTestId("partner-otp");
  return container;
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

// #579: the same read, ANSWERED instead of made to fail - the only way to get
// practice and specialty rows onto the handoff, since every other test in this
// file lets this read degrade to nulls. A stubbed transport rather than a
// module mock, so the rest of the suite keeps reaching the real client and its
// real shape guard: the projection below is the full shape precisely because
// that guard is what rejects a partial one. The client reads a bare JSON body.
function stubProfileRead(profile: DoctorProfileView) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(profile),
    }),
  );
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

  // #576: #572 rebuilt this step on the shared `OtpInput` atom, and the atom
  // carried a hardcoded English `aria-label` that outranks the step's localized
  // `FieldLabel`. `t` here is the English dictionary, so this suite cannot
  // observe the parity break by itself; what it can pin is that the name comes
  // from the dictionary at all, and that the invalid/error association the raw
  // input used to carry survived the swap. Together with the Hindi assertion in
  // `otp/shared.test.tsx`, that closes the gap.
  it("names the code field from the dictionary, not a literal (#576)", async () => {
    await startPartnerOtpFlow();
    const otp = screen.getByTestId("partner-otp");
    expect(otp).toHaveAttribute("aria-label", t.codeLabel);
    // And the visible label and the accessible name are the same string, so
    // reading the step in any locale hears what is on screen.
    expect(screen.getByText(t.codeLabel)).toBeInTheDocument();
  });

  it("marks the code field invalid and points it at the error the step renders (#576)", async () => {
    await startPartnerOtpFlow();
    // Fresh step, no error yet: nothing claimed.
    const otp = screen.getByTestId("partner-otp");
    expect(otp).not.toHaveAttribute("aria-invalid");
    expect(otp).not.toHaveAttribute("aria-describedby");

    vi.mocked(partnerVerify).mockResolvedValue(WRONG_CODE);
    typeCodeAndSubmit();
    const error = await screen.findByTestId("partner-error");
    // The `aria-describedby` target has to resolve to the rendered error, not
    // merely to a plausible-looking id.
    expect(otp).toHaveAttribute("aria-invalid", "true");
    expect(otp).toHaveAttribute("aria-describedby", "partner-error");
    expect(document.getElementById(otp.getAttribute("aria-describedby")!)).toBe(
      error,
    );
    expect(error).toHaveAttribute("role", "alert");
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

  // #573: the step's own heading and the scan over it. The page's heading and
  // the cross-stage count are NOT here - this suite renders the form bare, so
  // the page's `h1` is not in this DOM at all and could not be asserted on.
  // That half is `app/staff/login/page.test.tsx`, which renders the real page
  // around the real form. The split is what each DOM can see, not a dodge.
  it("carries its own top-level heading, the shared title class (#573 AC-1)", async () => {
    const container = await startPartnerOtpFlow();
    // An `h1` and not an `h2` or a `<p>`: "exactly one top-level heading per
    // stage" is only reachable if the steps that own one own it at level 1,
    // which is the treatment the patient wizard already gives this same step
    // (`PatientAuthWizard.tsx`).
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading.tagName).toBe("H1");
    expect(heading).toHaveTextContent(t.codeStepTitle);
    expect(heading).toHaveClass(stepStyles.title);
    // The step's own, and its only: the page's is not in this tree, so a second
    // one here would be a second owner, not the page's.
    expect(container.querySelectorAll("h1")).toHaveLength(1);
  });

  it("leaves the phone step with no heading of its own (#573 AC-5)", () => {
    // The page's "Sign in" is this step's heading, so a heading here too would
    // double it on the real page. Asserted bare, where the page's is absent.
    // Every level and the explicit role, since an ARIA heading is a heading.
    const { container } = render(<StaffLoginForm />);
    expect(
      container.querySelectorAll("h1,h2,h3,h4,h5,h6,[role=heading]"),
    ).toHaveLength(0);
  });

  it("scans clean on axe with the code step rendered (#573 AC-3)", async () => {
    // The seventh local scan in the tree, and the same shape as the patient
    // profile page's three: render, wait for the surface, run the scan on the
    // container. Scoped to the container rather than `document.body` because
    // this ticket owns the step, not the page's wordmark and register CTAs.
    // Note what it does and does not police: axe has no duplicate-`h1` rule, so
    // the heading count is a separate assertion and this scan is the guard on
    // the step's names, roles and live regions.
    const container = await startPartnerOtpFlow();
    expect((await axe.run(container)).violations).toEqual([]);
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
    // #579: a press is remembered rather than obeyed, and honoured the instant
    // the destination is in hand, so there is nothing to wait for first.
    // #581: the handoff no longer counts down, so there is no clock to wait out.
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
      // handoff's readiness conjunction is never satisfied and its one control
      // stays a no-op - asserted here rather than inferred from the routing
      // call, because a mocked location.replace never tears the tree down the
      // way a real hard navigation would. What
      // keeps the handoff from being the active-partner-only moment is the
      // routing, not a second render condition: the ticket freezes these three
      // exit branches, and the handoff is keyed to the OTP stage alone.
      expect(screen.queryByTestId("staff-submit")).not.toBeInTheDocument();
      expect(screen.queryByTestId("partner-otp")).not.toBeInTheDocument();
      // Held, because there is nowhere to go yet: the digit-free opening line,
      // and no navigation to a console path.
      expect(screen.getByRole("status").textContent).not.toMatch(/\d/);
      expect(mockRouterReplace).not.toHaveBeenCalled();
      // #579 AC-9: the flow is terminal here too, so the handoff is genuinely
      // mounted - the ticket's "never rendered" is a statement about the
      // browser, where the `location.replace` above swaps the document and takes
      // the tree with it, not about a tree that only a mocked replace keeps
      // alive. What must hold in BOTH worlds is that no console destination is
      // engaged: `landing` is never set, so readiness is never satisfied, and
      // the handoff's one control - wired to the go-now callback, not to the
      // navigate routine - cannot be a way around that. This is the assertion
      // that fails if a press ever latches a navigation the destination read
      // merely happened not to be guarding.
      expect(
        screen.getByRole("heading", { name: "Identity verified" }),
      ).toBeInTheDocument();
      fireEvent.click(screen.getByRole("button", { name: "Go to Dashboard" }));
      expect(mockRouterReplace).not.toHaveBeenCalled();
      expect(mockLocationReplace).toHaveBeenCalledWith(expected);
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

    // #579: the leave is the navigation hook's, on readiness, and a press is
    // remembered rather than obeyed, so the CTA is the drive and there is no
    // timer here to wait out. #581: the handoff carries no countdown at all.
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
    const alert = screen.getByRole("alert");
    // The envelope explanation AND its correlation reference, not the reference
    // alone: an alert carrying only a trace id would satisfy the waitFor above
    // and tell the partner nothing. (Which copy a NETWORK_ERROR maps to is the
    // error mapper's business, pinned in its own suite.)
    expect(alert).toHaveTextContent(t.invalidCredentials);
    expect(alert).toHaveTextContent("tr-landing");
    expect(
      screen.getByRole("heading", { name: "Identity verified" }),
    ).toBeInTheDocument();
    expect(screen.queryByTestId("staff-submit")).not.toBeInTheDocument();
    expect(screen.queryByTestId("partner-otp")).not.toBeInTheDocument();
    expect(mockLocationReplace).not.toHaveBeenCalled();
    // #579 AC-8: a destination that never resolves is a flow that is never
    // ready, so it navigates nothing - and the button, which is the one control
    // on this screen, must not be the way around it.
    fireEvent.click(screen.getByRole("button", { name: "Go to Dashboard" }));
    expect(mockRouterReplace).not.toHaveBeenCalled();
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
    // opening line, and no destination to go to yet.
    expect(
      screen.getByRole("heading", { level: 1, name: "Identity verified" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Opening your dashboard",
    );
    expect(screen.getByRole("status").textContent).not.toMatch(/\d/);
    // #581: the bar is indeterminate, so it announces a name and no values. A
    // surviving `aria-valuenow` would put a countdown back into the
    // accessibility tree on this very surface.
    expect(screen.getByRole("progressbar")).not.toHaveAttribute(
      "aria-valuenow",
    );
    expect(screen.getByRole("progressbar")).not.toHaveAttribute(
      "aria-valuetext",
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

// #579: the handoff leaves on READINESS, not on a countdown. The frozen screen
// this replaces shipped because nothing in the suite ever looked at the surface
// or the state between the destination resolving and the old five seconds
// expiring - every handoff test here was a `waitFor` on the settled end state.
// So these tests drive the gap directly: hold the destination read open, assert
// the INTERMEDIATE state synchronously, then let it land and assert the
// navigation. Deterministic throughout - no polling and no `waitFor` on the end
// state - and nothing here asserts on a countdown, because #581 removed the
// component's entirely. What the progress output carries is asserted as the
// absence of digits, which is the guarantee the ticket makes.
describe("StaffLoginForm - the handoff leaves on readiness (#579)", () => {
  // A span long enough to outlast any delay this screen could impose. The
  // negative assertions below advance past it to prove a clock decides nothing
  // here - ten seconds, twice what the handoff used to hold anyone for. #581
  // deleted that duration along with the countdown, so it is stated here in
  // milliseconds rather than imported from the component.
  const PAST_ANY_HANDOFF_DELAY_MS = 10_000;

  const goToDashboard = () =>
    screen.getByRole("button", { name: "Go to Dashboard" });

  // Drive the flow to the instant the handoff is up and the destination read is
  // still held open, with both of the handoff's clocks under the test's control.
  // The clocks are faked only here, and only AFTER the code step: the helper
  // reaches it with `findBy`, which polls on the real clock. Nothing downstream
  // needs the real clock - the destination read is a promise the test resolves
  // itself, and the handoff's leave is armed by readiness, which has not
  // happened while the read is held.
  //
  // A test installs whatever it needs to differ (a gated session resume, a
  // profile read that answers) BEFORE calling this, because the flow starts
  // inside it.
  async function holdDestinationOnTheHandoff() {
    const destination = holdDestinationRead();
    await completePartnerLoginOnPage();
    await destination.reached;
    vi.useFakeTimers({
      toFake: ["setInterval", "clearInterval", "setTimeout", "clearTimeout"],
    });
    await act(async () => {});
    return destination;
  }

  it("navigates to the console exactly once, and only once the destination lands (#579 AC-2/AC-3)", async () => {
    stubProfileRead(doctorProfile());
    const destination = await holdDestinationOnTheHandoff();

    // AC-2, the negative half and the one that matters. The session-resume seam
    // has long settled - `resumeSettled` is true - but the destination has not,
    // so nothing may move. Advancing twice the old five seconds proves it is
    // not the old countdown's clock that decides: a readiness boolean of just
    // `resumeSettled` fails exactly here and passes every other test here.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PAST_ANY_HANDOFF_DELAY_MS);
    });
    expect(mockRouterReplace).not.toHaveBeenCalled();
    // The active path is never a hard reload, whether or not the destination is
    // in hand.
    expect(mockLocationReplace).not.toHaveBeenCalled();
    // Started on the session, not on the resolved destination, and still one
    // call: the handoff is on screen and the resume seam has already run.
    expect(authState.resumeSession).toHaveBeenCalledTimes(1);
    // The progress output carries no countdown digits while there is nowhere to
    // go, and the bar is still at its opening value: nothing is counting down
    // towards a destination that does not exist.
    expect(screen.getByRole("status").textContent).not.toMatch(/\d/);

    // AC-3: both signals settled, so the leave happens - once, to the resolved
    // console route, through the framework router rather than a document swap.
    await act(async () => {
      destination.settle("Active");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HANDOFF_MINIMUM_DWELL_MS);
    });
    expect(mockRouterReplace).toHaveBeenCalledTimes(1);
    expect(mockRouterReplace).toHaveBeenCalledWith("/doctor");
    expect(mockLocationReplace).not.toHaveBeenCalled();
  });

  // #582: the regression case, and the reason #579 exists. The reported screen
  // was a handoff whose five seconds had expired while the destination was
  // still in flight: the timer had stopped, the auto-redirect had stopped with
  // it, and the button was wired to a routine that refused. Every one of those
  // three escapes was closed, so the partner had nothing left to press.
  //
  // It is pinned as TWO tests, not one, and the split is load-bearing rather
  // than tidier. A press on a handoff whose destination is still in flight sets
  // the hook's go-now ask, which drops the dwell on readiness - so a single test
  // that presses and then settles only ever exercises the go-now path. Folded
  // into one, it would still pass with the dwell-scheduled leave after a long
  // hold entirely broken, which is half the defect: the reported screen was not
  // one where the user pressed the button, it was one where nothing happened
  // until they did. The first test is the unattended path, the second is the
  // press, and the load-bearing name is on the unattended one.
  it("a destination slower than the old five-second hold still leaves exactly once, unattended (#579 AC-5)", async () => {
    stubProfileRead(doctorProfile());
    const destination = await holdDestinationOnTheHandoff();

    // The surface is live at the held instant, not just at the end of it: a
    // handoff that has already given up reads identically to one that is
    // waiting, which is exactly why this defect reached a production page.
    expect(goToDashboard()).toBeEnabled();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Identity verified",
    );

    // Twice the old hold, with nobody touching anything. Elapsed time is not
    // what releases this screen, so this is a long silence and not a leave.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PAST_ANY_HANDOFF_DELAY_MS);
    });
    expect(mockRouterReplace).not.toHaveBeenCalled();
    expect(mockLocationReplace).not.toHaveBeenCalled();
    // Still a live surface after the silence, with a control that still does
    // something the moment there is somewhere to go.
    expect(goToDashboard()).toBeEnabled();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(
      "Identity verified",
    );

    // The read finally lands, long after the old countdown would have expired
    // with its refuse already latched. The dwell is measured from this
    // readiness, not from mount, so the route is not pushed in the same
    // instant either.
    await act(async () => {
      destination.settle("Active");
    });
    // Flush the resume seam's microtask, so readiness is committed and the
    // dwell is armed, without moving the clock that will run it.
    await act(async () => {});
    expect(mockRouterReplace).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(HANDOFF_MINIMUM_DWELL_MS);
    });
    expect(mockRouterReplace).toHaveBeenCalledTimes(1);
    expect(mockRouterReplace).toHaveBeenCalledWith("/doctor");
    // Through the framework router rather than a document swap: the no-hard-
    // reload invariant is the one a frozen screen tempted people to break.
    expect(mockLocationReplace).not.toHaveBeenCalled();
    // One leave, ever - a second long wait adds no second navigation.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PAST_ANY_HANDOFF_DELAY_MS);
    });
    expect(mockRouterReplace).toHaveBeenCalledTimes(1);
  });

  it("a press on a handoff held as long as the old countdown is remembered, not lost (#579 AC-5)", async () => {
    stubProfileRead(doctorProfile());
    const destination = await holdDestinationOnTheHandoff();

    // Pressed mid-hold, long past the old countdown: the ask is remembered
    // rather than obeyed, because there is still nowhere to go. In the reported
    // defect this is the press that did nothing, forever.
    fireEvent.click(goToDashboard());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PAST_ANY_HANDOFF_DELAY_MS);
    });
    expect(mockRouterReplace).not.toHaveBeenCalled();
    expect(mockLocationReplace).not.toHaveBeenCalled();
    expect(goToDashboard()).toBeEnabled();

    // The read lands, the ask is honoured at once rather than after a beat, and
    // it happens exactly once.
    await act(async () => {
      destination.settle("Active");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(mockRouterReplace).toHaveBeenCalledTimes(1);
    expect(mockRouterReplace).toHaveBeenCalledWith("/doctor");
    expect(mockLocationReplace).not.toHaveBeenCalled();
  });

  it("cannot push the route before the session is in state (#579 AC-4)", async () => {
    stubProfileRead(doctorProfile());
    // The destination resolves on demand, and so does the session resume, so the
    // two signals can be separated. This is the ordering the ticket asks for -
    // the resume call precedes the route push - read as a consequence rather
    // than as an invocation order the memoized resume would satisfy anyway.
    let releaseResume!: () => void;
    const resumeGate = new Promise<void>((resolve) => {
      releaseResume = resolve;
    });
    authState.resumeSession.mockImplementation(() => resumeGate);
    const destination = await holdDestinationOnTheHandoff();

    // The destination is in hand and the session is not: nothing may navigate,
    // however long the flow waits. A destination-only readiness boolean fails
    // here.
    await act(async () => {
      destination.settle("Active");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HANDOFF_MINIMUM_DWELL_MS * 2);
    });
    expect(mockRouterReplace).not.toHaveBeenCalled();
    expect(mockLocationReplace).not.toHaveBeenCalled();

    // The session lands, and the route is pushed immediately behind it - once,
    // and to the resolved console route.
    await act(async () => {
      releaseResume();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HANDOFF_MINIMUM_DWELL_MS);
    });
    expect(mockRouterReplace).toHaveBeenCalledTimes(1);
    expect(mockRouterReplace).toHaveBeenCalledWith("/doctor");
  });

  it("honours the button at once, never before the destination, and never twice (#579 AC-6)", async () => {
    stubProfileRead(doctorProfile());
    const destination = await holdDestinationOnTheHandoff();

    // Pressed while there is nowhere to go, and pressed again: honoured as an
    // ask, not as a navigation. A button wired straight to the navigate routine
    // used to swallow both.
    fireEvent.click(goToDashboard());
    fireEvent.click(goToDashboard());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PAST_ANY_HANDOFF_DELAY_MS);
    });
    expect(mockRouterReplace).not.toHaveBeenCalled();

    // The destination lands, and the remembered ask means the leave skips the
    // dwell entirely.
    await act(async () => {
      destination.settle("Active");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(mockRouterReplace).toHaveBeenCalledTimes(1);

    // The button keeps being pressed after the navigation has begun, and the
    // hold this screen used to impose is given all the time it once owned: the
    // call count does not move. The hook's own once-only latch is what stops
    // it, and it is the only double-navigation hazard left now that the
    // handoff component owns no clock of its own.
    fireEvent.click(goToDashboard());
    fireEvent.click(goToDashboard());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(PAST_ANY_HANDOFF_DELAY_MS);
    });
    expect(mockRouterReplace).toHaveBeenCalledTimes(1);
  });

  // Two halves of one rule, stated as rows: what the landing knows, and the
  // values that must be on screen because of it.
  const factRows: Array<[string, Partial<DoctorProfileView>, string[]]> = [
    [
      "a profile that names the practice and specialty",
      {},
      ["Kumar Clinic", "General physician", "Doctor console"],
    ],
    [
      "a profile with neither",
      { practice_name: null, specialty: null },
      ["Doctor console"],
    ],
  ];

  it.each(factRows)(
    "shows the fact rows for %s, and skips whatever is absent (#579 AC-7)",
    async (_case, profileOverrides, expectedValues) => {
      stubProfileRead(doctorProfile(profileOverrides));
      const destination = await holdDestinationOnTheHandoff();

      // AC-7, the never-empty half: the bar and its message are up before any
      // fact is known, so the screen is never blank while the reads land.
      expect(screen.getByRole("progressbar")).toBeInTheDocument();
      expect(screen.getByRole("status")).toHaveTextContent(
        "Opening your dashboard",
      );
      expect(screen.queryByText("Practice")).not.toBeInTheDocument();

      await act(async () => {
        destination.settle("Active");
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });

      // Every known value is on screen, and the destination row is always
      // there - it is the one fact the landing always knows.
      for (const value of expectedValues) {
        expect(screen.getByText(value)).toBeInTheDocument();
      }
      expect(screen.getByText("Destination")).toBeInTheDocument();
      // Nothing rendered as a blank: an absent practice or specialty drops its
      // whole row, label included, rather than showing an empty one.
      for (const [label, value] of [
        ["Practice", profileOverrides.practice_name],
        ["Specialty", profileOverrides.specialty],
      ] as const) {
        if (value === null) {
          expect(screen.queryByText(label)).toBeNull();
        } else {
          expect(screen.getByText(label)).toBeInTheDocument();
        }
      }
    },
  );
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
