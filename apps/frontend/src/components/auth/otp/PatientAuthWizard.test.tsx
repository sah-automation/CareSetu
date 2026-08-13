// PHASE-2 T9 (ticket #60): frontend unit coverage for the patient auth wizard.
// Test names follow the ticket's acceptance criteria - register validation,
// verify states (wrong/expired/used), resend cooldown + latest-wins, lockout
// blocking, the duplicate-number notice, session storage landing on the
// authenticated view, and the hi/en toggle throughout.

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  issueSession,
  registerPhone,
  resendOtp,
  type RegisterResult,
  type SessionResult,
  verifyOtp,
  type VerifyResult,
} from "@/lib/auth/api";
import { PatientAuthWizard } from "./PatientAuthWizard";

vi.mock("@/lib/auth/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/auth/api")>();
  return {
    ...mod,
    registerPhone: vi.fn(),
    verifyOtp: vi.fn(),
    resendOtp: vi.fn(),
    issueSession: vi.fn(),
  };
});

const PHONE = "+919876543210";
const REGISTER_OK: RegisterResult = {
  phone_e164: PHONE,
  identity_id: 1,
  challenge_id: 11,
  is_existing: false,
  flow: "register",
  expires_in_seconds: 300,
  cooldown_remaining_seconds: 60,
  attempts_left: 5,
};

const REGISTER_DUPLICATE: RegisterResult = {
  ...REGISTER_OK,
  is_existing: true,
  flow: "login",
};

const SESSION: SessionResult = {
  jwt: "header.payload.signature",
  jti: "jti-1",
  scope: "patient",
  identity_id: 1,
  expires_in_seconds: 900,
  refresh_token: "opaque-refresh-token",
};

function verifiedResult(): VerifyResult {
  return {
    outcome: "verified",
    phone_e164: PHONE,
    identity_id: 1,
    attempts_left: null,
    lockout_remaining_seconds: null,
  };
}

async function enterPhone(digits = "9876543210") {
  fireEvent.change(
    await screen.findByPlaceholderText("10-digit mobile number"),
    { target: { value: digits } },
  );
}

async function startOtpFlow(
  registerResult: RegisterResult = REGISTER_OK,
): Promise<void> {
  vi.mocked(registerPhone).mockResolvedValue(registerResult);
  render(<PatientAuthWizard />);
  await enterPhone();
  fireEvent.click(
    screen.getByRole("button", { name: "Get verification code" }),
  );
  await screen.findByText(/6-digit code sent by SMS to/);
}

function typeOtp(digits = "123456") {
  fireEvent.change(screen.getByLabelText("Verification code"), {
    target: { value: digits },
  });
}

function verifyButton() {
  return screen.getByRole("button", { name: "Verify & continue" });
}

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  localStorage.clear();
  vi.mocked(registerPhone).mockReset();
  vi.mocked(verifyOtp).mockReset();
  vi.mocked(resendOtp).mockReset();
  vi.mocked(issueSession).mockReset();
});

describe("PatientAuthWizard - phone step", () => {
  it("renders the phone step once hydrated and does not call the API", async () => {
    render(<PatientAuthWizard />);

    expect(
      await screen.findByPlaceholderText("10-digit mobile number"),
    ).toBeInTheDocument();
    expect(registerPhone).not.toHaveBeenCalled();
  });

  it("shows the validation error for an invalid number and never calls the API", async () => {
    render(<PatientAuthWizard />);
    await enterPhone("123");

    fireEvent.click(
      screen.getByRole("button", { name: "Get verification code" }),
    );

    expect(
      await screen.findByText("Enter a valid 10-digit Indian mobile number."),
    ).toBeInTheDocument();
    expect(registerPhone).not.toHaveBeenCalled();
  });

  it("normalizes a valid number and moves to the verify step", async () => {
    await startOtpFlow();

    expect(registerPhone).toHaveBeenCalledWith(PHONE);
    expect(screen.getByText(PHONE)).toBeInTheDocument();
    expect(verifyButton()).toBeInTheDocument();
  });

  it("shows the already-registered login notice for a duplicate number", async () => {
    vi.mocked(registerPhone).mockResolvedValue(REGISTER_DUPLICATE);
    render(<PatientAuthWizard />);
    await enterPhone();
    fireEvent.click(
      screen.getByRole("button", { name: "Get verification code" }),
    );

    expect(
      await screen.findByText(
        "This number is already registered - verifying logs you in.",
      ),
    ).toBeInTheDocument();
  });
});

describe("PatientAuthWizard - verify step", () => {
  it("wrong code shows the attempts-left error", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue({
      outcome: "wrong_code",
      phone_e164: PHONE,
      identity_id: null,
      attempts_left: 4,
      lockout_remaining_seconds: null,
    });

    typeOtp("111111");
    fireEvent.click(verifyButton());

    expect(
      await screen.findByText("Wrong code. 4 attempts left."),
    ).toBeInTheDocument();
  });

  it("expired code shows the request-new-code message", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue({
      outcome: "expired",
      phone_e164: PHONE,
      identity_id: null,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });

    typeOtp("123456");
    fireEvent.click(verifyButton());

    expect(
      await screen.findByText(
        "This code has expired or was already used. Request a new one.",
      ),
    ).toBeInTheDocument();
  });

  it("used code shows the request-new-code message", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue({
      outcome: "spent",
      phone_e164: PHONE,
      identity_id: null,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });

    typeOtp("123456");
    fireEvent.click(verifyButton());

    expect(
      await screen.findByText(
        "This code has expired or was already used. Request a new one.",
      ),
    ).toBeInTheDocument();
  });

  it("zero attempts left renders the request-a-new-code hint", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue({
      outcome: "wrong_code",
      phone_e164: PHONE,
      identity_id: null,
      attempts_left: 0,
      lockout_remaining_seconds: null,
    });

    typeOtp("111111");
    fireEvent.click(verifyButton());

    expect(
      await screen.findByText("No attempts left. Request a new code."),
    ).toBeInTheDocument();
  });

  it("lockout state renders the lockout message and blocks input", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue({
      outcome: "locked",
      phone_e164: PHONE,
      identity_id: null,
      attempts_left: null,
      lockout_remaining_seconds: 900,
    });

    typeOtp("123456");
    fireEvent.click(verifyButton());

    expect(
      await screen.findByText(
        "Too many failed attempts. Verification locked for 15 min.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Verification code")).toBeDisabled();
  });

  it("disables resend while the cooldown is active", async () => {
    await startOtpFlow();

    const resend = screen.getByRole("button", { name: "Resend code" });
    expect(resend).toBeDisabled();
    fireEvent.click(resend);
    expect(resendOtp).not.toHaveBeenCalled();
  });

  it("resend past the cooldown shows the latest-wins notice", async () => {
    await startOtpFlow({
      ...REGISTER_OK,
      cooldown_remaining_seconds: 0,
    });
    vi.mocked(resendOtp).mockResolvedValue({
      outcome: "sent",
      phone_e164: PHONE,
      challenge_id: 12,
      expires_in_seconds: 300,
      cooldown_remaining_seconds: 60,
      lockout_remaining_seconds: null,
      attempts_left: 5,
    });

    const resend = screen.getByRole("button", { name: "Resend code" });
    expect(resend).toBeEnabled();
    fireEvent.click(resend);

    expect(
      await screen.findByText(
        "A new code was sent. The previous code is no longer valid.",
      ),
    ).toBeInTheDocument();
  });
});

describe("PatientAuthWizard - resend refuse states", () => {
  it("cooldown outcome shows the cooldown countdown", async () => {
    await startOtpFlow({ ...REGISTER_OK, cooldown_remaining_seconds: 0 });
    vi.mocked(resendOtp).mockResolvedValue({
      outcome: "cooldown",
      phone_e164: PHONE,
      challenge_id: null,
      expires_in_seconds: null,
      cooldown_remaining_seconds: 60,
      lockout_remaining_seconds: null,
      attempts_left: null,
    });

    fireEvent.click(screen.getByRole("button", { name: "Resend code" }));

    expect(
      await screen.findByText("Cooldown active. Resend in 60s."),
    ).toBeInTheDocument();
  });

  it("locked outcome renders the lockout and blocks input", async () => {
    await startOtpFlow({ ...REGISTER_OK, cooldown_remaining_seconds: 0 });
    vi.mocked(resendOtp).mockResolvedValue({
      outcome: "locked",
      phone_e164: PHONE,
      challenge_id: null,
      expires_in_seconds: null,
      cooldown_remaining_seconds: null,
      lockout_remaining_seconds: 900,
      attempts_left: null,
    });

    fireEvent.click(screen.getByRole("button", { name: "Resend code" }));

    expect(
      await screen.findByText(
        "Too many failed attempts. Verification locked for 15 min.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Verification code")).toBeDisabled();
  });

  it("suspended outcome shows the suspended notice", async () => {
    await startOtpFlow({ ...REGISTER_OK, cooldown_remaining_seconds: 0 });
    vi.mocked(resendOtp).mockResolvedValue({
      outcome: "suspended",
      phone_e164: PHONE,
      challenge_id: null,
      expires_in_seconds: null,
      cooldown_remaining_seconds: null,
      lockout_remaining_seconds: null,
      attempts_left: null,
    });

    fireEvent.click(screen.getByRole("button", { name: "Resend code" }));

    expect(
      await screen.findByText(
        "This number is suspended. Contact support for assistance.",
      ),
    ).toBeInTheDocument();
  });

  it("no-identity outcome returns to the phone step with the notice", async () => {
    await startOtpFlow({ ...REGISTER_OK, cooldown_remaining_seconds: 0 });
    vi.mocked(resendOtp).mockResolvedValue({
      outcome: "no_identity",
      phone_e164: PHONE,
      challenge_id: null,
      expires_in_seconds: null,
      cooldown_remaining_seconds: null,
      lockout_remaining_seconds: null,
      attempts_left: null,
    });

    fireEvent.click(screen.getByRole("button", { name: "Resend code" }));

    expect(
      await screen.findByText(
        "This number was never registered. Go back and get a code first.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("10-digit mobile number"),
    ).toBeInTheDocument();
  });
});

describe("PatientAuthWizard - success and session", () => {
  it("stores the session, shows the Done step, and lands on the authenticated home", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue(verifiedResult());
    vi.mocked(issueSession).mockResolvedValue(SESSION);

    typeOtp();
    fireEvent.click(verifyButton());

    expect(await screen.findByText("Identity verified")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Go to CareSetu home" }),
    );

    expect(await screen.findByText("You're signed in")).toBeInTheDocument();
    expect(screen.getByText(`Signed in as ${PHONE}`)).toBeInTheDocument();
    expect(issueSession).toHaveBeenCalledWith(PHONE);

    const stored = JSON.parse(localStorage.getItem("caresetu.session") ?? "{}");
    expect(stored.jwt).toBe("header.payload.signature");
    expect(stored.refresh_token).toBe("opaque-refresh-token");
  });

  it("a stored session lands directly on the authenticated home without API calls", async () => {
    localStorage.setItem(
      "caresetu.session",
      JSON.stringify({
        jwt: "header.payload.signature",
        refresh_token: "opaque-refresh-token",
        jti: "jti-1",
        scope: "patient",
        identity_id: 1,
        phone: PHONE,
      }),
    );

    render(<PatientAuthWizard />);

    expect(await screen.findByText("You're signed in")).toBeInTheDocument();
    expect(registerPhone).not.toHaveBeenCalled();
  });

  it("signing out returns to the phone step and clears the session", async () => {
    await startOtpFlow();
    vi.mocked(verifyOtp).mockResolvedValue(verifiedResult());
    vi.mocked(issueSession).mockResolvedValue(SESSION);
    typeOtp();
    fireEvent.click(verifyButton());
    await screen.findByText("Identity verified");
    fireEvent.click(
      screen.getByRole("button", { name: "Go to CareSetu home" }),
    );
    await screen.findByText("You're signed in");

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    expect(
      await screen.findByPlaceholderText("10-digit mobile number"),
    ).toBeInTheDocument();
    expect(localStorage.getItem("caresetu.session")).toBeNull();
  });
});

describe("PatientAuthWizard - language toggle", () => {
  it("switches to Hindi and back to English across steps", async () => {
    render(<PatientAuthWizard />);
    await screen.findByPlaceholderText("10-digit mobile number");

    fireEvent.click(screen.getByRole("button", { name: "हिंदी" }));
    expect(
      await screen.findByPlaceholderText("10 अंकों का मोबाइल नंबर"),
    ).toBeInTheDocument();

    vi.mocked(registerPhone).mockResolvedValue(REGISTER_OK);
    fireEvent.change(screen.getByPlaceholderText("10 अंकों का मोबाइल नंबर"), {
      target: { value: "9876543210" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "वेरिफिकेशन कोड पाएँ" }),
    );
    await screen.findByText(/SMS से भेजा गया 6 अंकों का कोड/);

    fireEvent.click(screen.getByRole("button", { name: "EN" }));
    expect(
      screen.getByRole("button", { name: "Resend code" }),
    ).toBeInTheDocument();
  });
});
