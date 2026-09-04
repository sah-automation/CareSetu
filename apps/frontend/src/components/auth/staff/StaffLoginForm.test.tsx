// PHASE-2.6 T10 (#201): staff login card behavior - phone/email dual-mode
// form and honest submit feedback (done-verify suite).
//
// PHASE-5 T4 (#282): operator login flow tests - phone+password triggers
// operatorLogin, SESSION_MFA_REQUIRED surfaces TOTP step, successful MFA
// creates session and routes via postLoginTarget.

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-errors";
import { STRINGS } from "@/lib/i18n/dictionaries";

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

const mockFetchMe = vi.fn();
vi.mock("@/lib/auth/api", () => ({
  fetchMe: (...args: unknown[]) => mockFetchMe(...args),
}));

const mockSaveSession = vi.fn();
vi.mock("@/lib/auth/session", () => ({
  saveSession: (...args: unknown[]) => mockSaveSession(...args),
}));

const mockPostLoginTarget = vi.fn().mockReturnValue("/operator/home");
vi.mock("@/lib/auth/staff-routing", () => ({
  postLoginTarget: (...args: unknown[]) => mockPostLoginTarget(...args),
}));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  mockLocationReplace.mockClear();
});

const t = STRINGS.en.staffAuth.login;

function fillPhoneAndTotp() {
  fireEvent.change(screen.getByTestId("staff-phone"), {
    target: { value: "9876543210" },
  });
  fireEvent.change(screen.getByTestId("staff-totp"), {
    target: { value: "123456" },
  });
}

function fillEmailAndPass() {
  fireEvent.change(screen.getByTestId("staff-email"), {
    target: { value: "dr.sharma@example.com" },
  });
  fireEvent.change(screen.getByTestId("staff-password"), {
    target: { value: "secret" },
  });
}

describe("StaffLoginForm", () => {
  it("renders phone field, and email+password when phone is empty", () => {
    render(<StaffLoginForm />);
    expect(screen.getByTestId("staff-phone")).toBeInTheDocument();
    expect(screen.getByTestId("staff-email")).toBeInTheDocument();
    expect(screen.getByTestId("staff-password")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /doctor|lab|chemist/i }),
    ).not.toBeInTheDocument();
  });

  it("renders TOTP input instead of email+password when phone is filled", () => {
    render(<StaffLoginForm />);
    fireEvent.change(screen.getByTestId("staff-phone"), {
      target: { value: "9876543210" },
    });
    expect(screen.getByTestId("staff-totp")).toBeInTheDocument();
    expect(screen.queryByTestId("staff-email")).not.toBeInTheDocument();
    expect(screen.queryByTestId("staff-password")).not.toBeInTheDocument();
  });

  it("keeps the forgot-password link as a placeholder", () => {
    render(<StaffLoginForm />);
    const link = screen.getByTestId("forgot-password");
    expect(link).toHaveTextContent(t.forgotPassword);
  });

  it("toggles password visibility through the labeled control in partner mode", () => {
    render(<StaffLoginForm />);
    // Password toggle is only visible when phone is empty (partner mode).
    const input = screen.getByTestId("staff-password");
    const toggle = screen.getByTestId("password-toggle");
    expect(input).toHaveAttribute("type", "password");
    fireEvent.click(toggle);
    expect(input).toHaveAttribute("type", "text");
    expect(toggle).toHaveAttribute("aria-label", t.hidePassword);
    fireEvent.click(toggle);
    expect(input).toHaveAttribute("type", "password");
    expect(toggle).toHaveAttribute("aria-label", t.showPassword);
  });

  it("validates phone on blur", () => {
    render(<StaffLoginForm />);
    fireEvent.change(screen.getByTestId("staff-phone"), {
      target: { value: "123" },
    });
    fireEvent.blur(screen.getByTestId("staff-phone"));
    expect(screen.getByTestId("staff-phone-error")).toHaveTextContent(
      t.phoneInvalid,
    );
  });

  it("validates TOTP code on blur in operator mode", () => {
    render(<StaffLoginForm />);
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

  it("validates email on blur", () => {
    render(<StaffLoginForm />);
    fireEvent.blur(screen.getByTestId("staff-email"));
    expect(screen.getByTestId("staff-email-error")).toHaveTextContent(
      t.emailInvalid,
    );
  });

  it("summarizes invalid submits with a count", () => {
    render(<StaffLoginForm />);
    fireEvent.click(screen.getByTestId("staff-submit"));
    expect(screen.getByTestId("staff-form-summary")).toBeInTheDocument();
  });

  it("submits honestly when only email+password filled (partner path)", () => {
    render(<StaffLoginForm />);
    fillEmailAndPass();
    fireEvent.click(screen.getByTestId("staff-submit"));
    expect(screen.getByTestId("staff-phase5-notice")).toBeInTheDocument();
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
    mockFetchMe.mockResolvedValue({
      identity_id: 5,
      phone: "+919876543210",
      roles: ["operator"],
    });

    render(<StaffLoginForm />);
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
    mockFetchMe.mockResolvedValue({
      identity_id: 5,
      phone: "+919876543210",
      roles: ["operator"],
    });

    render(<StaffLoginForm />);
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
    render(<StaffLoginForm />);
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
    render(<StaffLoginForm />);
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
    render(<StaffLoginForm />);
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
    mockFetchMe.mockResolvedValue({
      identity_id: 5,
      phone: "+919876543210",
      roles: ["operator"],
    });

    render(<StaffLoginForm />);
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

    render(<StaffLoginForm />);
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

    render(<StaffLoginForm />);
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

    render(<StaffLoginForm />);
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

    render(<StaffLoginForm />);
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

    render(<StaffLoginForm />);
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

  it("does not call operatorLogin when phone is empty", async () => {
    render(<StaffLoginForm />);
    fillEmailAndPass();
    fireEvent.click(screen.getByTestId("staff-submit"));

    // Partner path - no operatorLogin call
    expect(mockOperatorLogin).not.toHaveBeenCalled();
  });
});
