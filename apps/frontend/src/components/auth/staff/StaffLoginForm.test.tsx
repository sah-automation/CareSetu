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

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
import type { PartnerStatus } from "@/lib/partner/api";

import { StaffLoginForm } from "./StaffLoginForm";

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

const { mockFetchPartnerMe } = vi.hoisted(() => ({
  mockFetchPartnerMe: vi.fn(),
}));
vi.mock("@/lib/partner/api", () => ({
  fetchPartnerMe: (...args: unknown[]) => mockFetchPartnerMe(...args),
}));

const mockPostLoginTarget = vi.fn().mockReturnValue("/operator/home");
vi.mock("@/lib/auth/staff-routing", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/auth/staff-routing")>();
  return {
    ...mod,
    postLoginTarget: (...args: unknown[]) => mockPostLoginTarget(...args),
  };
});

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
  vi.clearAllMocks();
  mockLocationReplace.mockClear();
});

beforeEach(() => {
  vi.mocked(fetchMe).mockReset();
  vi.mocked(fetchDemoOtp).mockReset();
  vi.mocked(issuePartnerSession).mockReset();
  vi.mocked(issueSession).mockReset();
  vi.mocked(registerPhone).mockReset();
  vi.mocked(verifyOtp).mockReset();
  vi.mocked(partnerLogin).mockReset();
  vi.mocked(partnerVerify).mockReset();
  mockOperatorLogin.mockReset();
  mockSaveSession.mockReset();
  mockPostLoginTarget.mockReset().mockReturnValue("/operator/home");
  // Default an already-active partner so role-less landing assertions in the
  // generic flow stay deterministic.
  mockFetchPartnerMe.mockReset().mockResolvedValue({
    partner_id: 7,
    partner_type: "doctor",
    round: 1,
    status: "Active",
  });
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

  it("verifies the code, mints a partner session, and routes to /partner", async () => {
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
      });
      expect(mockLocationReplace).toHaveBeenCalledWith("/partner");
    });

    // The patient lifecycle is never touched for a partner sign-in.
    expect(vi.mocked(issueSession)).not.toHaveBeenCalled();
    expect(vi.mocked(registerPhone)).not.toHaveBeenCalled();
    expect(vi.mocked(verifyOtp)).not.toHaveBeenCalled();
  });

  async function completePartnerLogin(status: PartnerStatus) {
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
      status,
    });
    render(<StaffLoginForm />);
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
        });
        expect(mockLocationReplace).toHaveBeenCalledWith(expected);
      });
    },
  );

  it("derives no partnerState for an active partner and lands role-based", async () => {
    mockPostLoginTarget.mockReturnValue("/partner");
    await completePartnerLogin("Active");

    await waitFor(() => {
      expect(mockFetchPartnerMe).toHaveBeenCalled();
      expect(mockPostLoginTarget).toHaveBeenCalledWith({
        surface: "staff",
        roles: ["partner"],
        partnerState: undefined,
      });
      expect(mockLocationReplace).toHaveBeenCalledWith("/partner");
    });
  });

  it("falls back to role-based routing when the partner status read fails", async () => {
    mockPostLoginTarget.mockReturnValue("/partner");
    mockFetchPartnerMe.mockRejectedValue(
      new ApiError({
        code: "NETWORK_ERROR",
        message: "down",
        trace_id: "tr-partner-me",
        details: {},
      }),
    );
    await completePartnerLogin("Active");

    await waitFor(() => {
      expect(mockPostLoginTarget).toHaveBeenCalledWith({
        surface: "staff",
        roles: ["partner"],
        partnerState: undefined,
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
    expect(mockLocationReplace).not.toHaveBeenCalled();
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
