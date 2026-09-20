// PHASE-2.6 T11 (#202): component suite for the four-step provider
// registration wizard. Covers the ticket's acceptance criteria: four steps
// in order, the ?type= CTA preset flow, per-field validation blocking
// progression, upload-discipline checks, and real submission to the backend.

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ProviderRegisterWizard } from "./ProviderRegisterWizard";
import { COUNCIL_OPTION_IDS } from "./providerRegisterState";
import { STRINGS } from "@/lib/i18n/dictionaries";
import { __resetLangForTests, useLang } from "@/lib/i18n/LangContext";

import { registerPartner, submitCredentials } from "@/lib/partner/api";
import {
  fetchDemoOtp,
  issuePartnerSession,
  partnerLogin,
  partnerVerify,
  type PartnerLoginResult,
  type PartnerVerifyResult,
} from "@/lib/auth/api";
import { saveSession } from "@/lib/auth/session";
import { postLoginTarget } from "@/lib/auth/staff-routing";

vi.mock("@/lib/partner/api", () => ({
  registerPartner: vi.fn().mockResolvedValue({
    partner_id: 1,
    identity_id: 1,
    partner_type: "doctor",
    status: "Registered",
    round: 1,
    created: true,
  }),
  submitCredentials: vi.fn().mockResolvedValue({
    partner_id: 1,
    status: "Registered",
    round: 1,
  }),
}));

vi.mock("@/lib/auth/api", () => ({
  issuePartnerSession: vi.fn().mockResolvedValue({
    jwt: "test-jwt",
    jti: "test-jti",
    scope: "partner",
    identity_id: 1,
    expires_in_seconds: 3600,
    refresh_token: "test-refresh",
  }),
  partnerLogin: vi.fn(),
  partnerVerify: vi.fn(),
  fetchDemoOtp: vi.fn(),
  AuthApiError: class MockAuthApiError extends Error {
    readonly code: string;
    readonly details: Record<string, unknown>;
    readonly traceId: string;
    constructor(envelope: {
      code: string;
      message: string;
      trace_id: string;
      details: Record<string, unknown>;
    }) {
      super(envelope.message);
      this.name = "AuthApiError";
      this.code = envelope.code;
      this.details = envelope.details;
      this.traceId = envelope.trace_id;
    }
  },
}));

vi.mock("@/lib/auth/session", () => ({
  saveSession: vi.fn(),
}));

vi.mock("@/lib/auth/staff-routing", () => ({
  postLoginTarget: vi.fn().mockReturnValue("/partner/status/pending"),
}));

const t = STRINGS.en.staffAuth.register;
const loginT = STRINGS.en.staffAuth.login;
const STRONG = "correct-horse-battery1!";

const mockRegisterPartner = vi.mocked(registerPartner);
const mockSubmitCredentials = vi.mocked(submitCredentials);
const mockIssuePartnerSession = vi.mocked(issuePartnerSession);
const mockSaveSession = vi.mocked(saveSession);
const mockPostLoginTarget = vi.mocked(postLoginTarget);
const mockPartnerLogin = vi.mocked(partnerLogin);
const mockPartnerVerify = vi.mocked(partnerVerify);
const mockFetchDemoOtp = vi.mocked(fetchDemoOtp);

// The confirmation step's phone-OTP flow (partnerLoginState.ts) default
// transcripts: challenge issued -> code verified -> session minted.
const CONFIRM_LOGIN_OK: PartnerLoginResult = {
  outcome: "sent",
  phone_e164: "+919876543210",
  challenge_id: 1,
  expires_in_seconds: 300,
  cooldown_remaining_seconds: 60,
  attempts_left: 5,
  lockout_remaining_seconds: null,
};
const CONFIRM_VERIFY_OK: PartnerVerifyResult = {
  outcome: "verified",
  phone_e164: "+919876543210",
  identity_id: 1,
  attempts_left: 5,
  lockout_remaining_seconds: null,
};

function mockGeolocation(
  handler: (
    success: (position: {
      coords: { latitude: number; longitude: number };
    }) => void,
    error: (err: { code: number; message: string }) => void,
  ) => void,
) {
  vi.stubGlobal("navigator", {
    geolocation: {
      getCurrentPosition: vi.fn().mockImplementation(handler),
    },
  });
}

// Flip the app locale through the shared language store, exactly like the
// other bilingual suites (ProfileNudges, ProviderProfile).
function LangFlip() {
  const { lang, setLang } = useLang();
  return (
    <button
      type="button"
      data-testid="lang-flip"
      onClick={() => setLang(lang === "en" ? "hi" : "en")}
    >
      flip
    </button>
  );
}

beforeEach(() => {
  vi.stubGlobal(
    "FileReader",
    class {
      result: string | null = null;
      onload: (() => void) | null = null;
      readAsDataURL(_blob: Blob) {
        this.result = "data:application/octet-stream;base64,dGVzdA==";
        if (this.onload) this.onload();
      }
    },
  );

  // Mock navigator.geolocation for wizard submit tests - default resolves
  // with a fixed position distinct from (0,0).
  mockGeolocation((success) => {
    success({
      coords: {
        latitude: 23.99,
        longitude: 83.99,
      },
    });
  });

  // Give the confirmation step's OTP flow its default happy transcript;
  // per-test overrides (wrong code, refusals) win via mockResolvedValueOnce.
  mockPartnerLogin.mockReset().mockResolvedValue(CONFIRM_LOGIN_OK);
  mockPartnerVerify.mockReset().mockResolvedValue(CONFIRM_VERIFY_OK);
  mockFetchDemoOtp.mockReset().mockResolvedValue(null);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  __resetLangForTests();
  mockPostLoginTarget.mockClear();
});

function type(testId: string, value: string) {
  fireEvent.change(screen.getByTestId(testId), {
    target: { value },
  });
}

function attachFile(testId: string, file: File) {
  const input = screen.getByTestId(testId) as HTMLInputElement;
  Object.defineProperty(input, "files", { value: [file] });
  fireEvent.change(input);
}

function fillStep1() {
  type("pr-fullname", "Dr. Asha Kumar");
  type("pr-email", "asha@example.com");
  type("pr-password", STRONG);
  type("pr-mobile", "9876543210");
}

function fillDoctorStep2() {
  type("pr-degreename", "Dr. Asha Kumar");
  // Options carry stable ids; the review step renders the localized label.
  fireEvent.change(screen.getByTestId("pr-council"), {
    target: { value: COUNCIL_OPTION_IDS[0] },
  });
  type("pr-city", "Daltonganj");
  type("pr-languages", "Hindi, English");
}

function attachDoctorFiles() {
  attachFile(
    "slot-input-councilCert",
    new File(["cert"], "council-cert.pdf", { type: "application/pdf" }),
  );
  attachFile(
    "slot-input-degrees",
    new File(["mbbs"], "mbbs-degree.jpg", { type: "image/jpeg" }),
  );
  attachFile(
    "slot-input-photoId",
    new File(["aadhaar"], "aadhaar.png", { type: "image/png" }),
  );
}

function walkToStep(
  step: number,
  applicationType: "doctor" | "lab" | "chemist",
) {
  render(<ProviderRegisterWizard presetType={applicationType} />);
  if (step > 1) {
    fillStep1();
    fireEvent.click(screen.getByTestId("pr-next"));
  }
  if (step > 2) {
    if (applicationType === "doctor") {
      fillDoctorStep2();
    } else {
      type("pr-businessname", "Seva Diagnostics");
      type("pr-address", "Main Road, Daltonganj");
      type("pr-servicearea", "Daltonganj + 15 km");
      type("pr-ownercontact", "9876543210");
    }
    fireEvent.click(screen.getByTestId("pr-next"));
  }
  if (step > 3) {
    if (applicationType === "doctor") {
      attachDoctorFiles();
    } else {
      attachFile(
        "slot-input-businessReg",
        new File(["gst"], "gst.pdf", { type: "application/pdf" }),
      );
      attachFile(
        "slot-input-kyc",
        new File(["kyc"], "kyc.pdf", { type: "application/pdf" }),
      );
    }
    fireEvent.click(screen.getByTestId("pr-next"));
  }
  return screen.getByTestId(`pr-step-${Math.min(step, 4)}`);
}

// Walk the doctor wizard through review, tick every declaration, submit the
// application, and land on the phone-confirmation step (F014-T08 #468). The
// submit click is wrapped in act: registration resolves on a microtask and
// React 18 batches the step transition, so the flush makes it deterministic.
async function submitToConfirm(
  mobileOverride?: string,
  renderOverride?: () => void,
) {
  if (renderOverride) {
    renderOverride();
  } else {
    walkToStep(1, "doctor");
  }
  fillStep1();
  if (mobileOverride) {
    type("pr-mobile", mobileOverride);
  }
  fireEvent.click(screen.getByTestId("pr-next"));
  fillDoctorStep2();
  fireEvent.click(screen.getByTestId("pr-next"));
  attachDoctorFiles();
  fireEvent.click(screen.getByTestId("pr-next"));
  fireEvent.click(screen.getByTestId("decl-truth"));
  fireEvent.click(screen.getByTestId("decl-consent"));
  fireEvent.click(screen.getByTestId("decl-terms"));
  await act(async () => {
    fireEvent.click(screen.getByTestId("pr-submit"));
  });
  await screen.findByTestId("pr-step-5");
}

// Enter the SMS code on the confirmation step and click Confirm code. The
// click is wrapped in act: minting happens in a promise continuation (the
// shared partner flow), so the async flush is needed for a deterministic DOM.
async function confirmWithCode(digits = "123456") {
  type("pr-confirm-otp", digits);
  await act(async () => {
    fireEvent.click(screen.getByTestId("pr-confirm-submit"));
  });
}

describe("four-step skeleton (blueprint §4.3)", () => {
  it("renders the four steps in order with step 1 current", () => {
    walkToStep(1, "doctor");
    const stepper = screen.getByTestId("pr-stepper");
    expect(stepper).toBeInTheDocument();
    expect(screen.getByTestId("pr-step-1")).toHaveTextContent(t.accountTitle);
    expect(screen.queryByTestId("pr-step-2")).not.toBeInTheDocument();
    expect(screen.getByTestId("pr-back")).toBeDisabled();
    const items = within(stepper).getAllByRole("listitem");
    expect(items).toHaveLength(t.steps.length);
    expect(items[0]).toHaveAttribute("aria-current", "step");
    expect(items[0]).toHaveTextContent(t.steps[0]);
  });

  it("advances Continue through every step to Submit application", () => {
    walkToStep(4, "doctor");
    expect(screen.getByTestId("pr-step-4")).toBeInTheDocument();
    expect(screen.getByTestId("pr-submit")).toHaveTextContent(
      t.submitApplication,
    );
  });

  it("goes Back without losing entered values", () => {
    walkToStep(2, "doctor");
    fireEvent.click(screen.getByTestId("pr-back"));
    expect(screen.getByTestId("pr-step-1")).toBeInTheDocument();
    expect(screen.getByTestId("pr-fullname")).toHaveValue("Dr. Asha Kumar");
  });
});

describe("type preset carried from the CTA query param", () => {
  it("pre-selects the doctor application by default when absent", () => {
    walkToStep(1, "doctor");
    expect(screen.getByTestId("pr-type-badge")).toHaveTextContent(
      t.typeBadge.doctor,
    );
  });

  it("pre-selects lab and shows business identity instead of doctor fields", () => {
    walkToStep(2, "lab");
    expect(screen.getByTestId("pr-type-badge")).toHaveTextContent(
      t.typeBadge.lab,
    );
    expect(
      screen.getByRole("heading", { name: t.identityTitlePartner }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("pr-businessname")).toBeInTheDocument();
    expect(screen.queryByTestId("pr-degreename")).not.toBeInTheDocument();
  });

  it("pre-selects chemist and lists its credential slots", () => {
    walkToStep(3, "chemist");
    expect(screen.getByTestId("pr-type-badge")).toHaveTextContent(
      t.typeBadge.chemist,
    );
    expect(screen.getByTestId("slot-drugLicense")).toBeInTheDocument();
    expect(screen.getByTestId("slot-shopLicense")).toBeInTheDocument();
    expect(screen.getByTestId("slot-kyc")).toBeInTheDocument();
    expect(screen.queryByTestId("slot-councilCert")).not.toBeInTheDocument();
  });

  it("falls back to doctor on a junk preset", () => {
    render(<ProviderRegisterWizard presetType="hacker" />);
    expect(screen.getByTestId("pr-type-badge")).toHaveTextContent(
      t.typeBadge.doctor,
    );
  });
});

describe("validation blocks progression with per-field messages", () => {
  it("blocks an empty step 1 and renders each field's message plus summary", () => {
    walkToStep(1, "doctor");
    fireEvent.click(screen.getByTestId("pr-next"));
    expect(screen.getByTestId("pr-step-1")).toBeInTheDocument();
    expect(screen.getByTestId("pr-fullname-error")).toHaveTextContent(
      t.errors.fullNameRequired,
    );
    expect(screen.getByTestId("pr-email-error")).toHaveTextContent(
      t.errors.emailInvalid,
    );
    expect(screen.getByTestId("pr-password-error")).toHaveTextContent(
      t.errors.passwordWeak,
    );
    expect(screen.getByTestId("pr-mobile-error")).toHaveTextContent(
      t.errors.mobileRequired,
    );
    expect(screen.getByTestId("pr-form-summary")).toHaveTextContent(
      t.summaryTitle(4),
    );
  });

  it("blocks a weak password even when other fields are fine", () => {
    walkToStep(1, "doctor");
    type("pr-fullname", "Dr. Asha Kumar");
    type("pr-email", "asha@example.com");
    type("pr-password", "weakpass");
    fireEvent.click(screen.getByTestId("pr-next"));
    expect(screen.getByTestId("pr-step-1")).toBeInTheDocument();
    expect(screen.getByTestId("pr-password-error")).toBeInTheDocument();
    // The strength meter reflects typed progress.
    expect(
      parseInt(
        (screen.getByTestId("pw-strength") as HTMLElement).style.width,
        10,
      ),
    ).toBeGreaterThan(0);
  });

  it("validates a single field on blur before any submit attempt", () => {
    walkToStep(1, "doctor");
    type("pr-email", "not-an-email");
    fireEvent.blur(screen.getByTestId("pr-email"));
    expect(screen.getByTestId("pr-email-error")).toHaveTextContent(
      t.errors.emailInvalid,
    );
    expect(screen.queryByTestId("pr-form-summary")).not.toBeInTheDocument();
  });

  it("blocks an incomplete doctor identity step", () => {
    walkToStep(2, "doctor");
    fireEvent.click(screen.getByTestId("pr-next"));
    expect(screen.getByTestId("pr-step-2")).toBeInTheDocument();
    expect(screen.getByTestId("pr-council-error")).toHaveTextContent(
      t.errors.councilRequired,
    );
  });

  it("blocks an incomplete partner identity step", () => {
    walkToStep(2, "chemist");
    type("pr-businessname", "Seva Chemist");
    fireEvent.click(screen.getByTestId("pr-next"));
    expect(screen.getByTestId("pr-step-2")).toBeInTheDocument();
    expect(screen.getByTestId("pr-ownercontact-error")).toHaveTextContent(
      t.errors.ownerContactInvalid,
    );
  });
});

describe("credentials upload discipline", () => {
  it("shows the chosen document with its size after explicit selection", () => {
    walkToStep(3, "doctor");
    attachDoctorFiles();
    expect(screen.getByTestId("slot-file-councilCert")).toHaveTextContent(
      "council-cert.pdf",
    );
    expect(screen.getByTestId("slot-file-degrees")).toHaveTextContent(
      "mbbs-degree.jpg (4 B)",
    );
  });

  it("rejects disallowed file types with a per-slot message", () => {
    walkToStep(3, "doctor");
    attachFile(
      "slot-input-councilCert",
      new File(["evil"], "evil.exe", { type: "" }),
    );
    expect(screen.getByTestId("slot-error-councilCert")).toHaveTextContent(
      t.errors.uploadWrongType,
    );
    // The rejected file never became an attachment, so advancing re-checks
    // the slot and blocks with the missing-document message.
    fireEvent.click(screen.getByTestId("pr-next"));
    expect(screen.getByTestId("pr-step-3")).toBeInTheDocument();
    expect(screen.getByTestId("slot-error-councilCert")).toHaveTextContent(
      t.errors.uploadRequired,
    );
  });

  it("rejects oversized files with the size message", () => {
    walkToStep(3, "doctor");
    const huge = new File([new ArrayBuffer(8)], "huge.pdf", {
      type: "application/pdf",
    });
    Object.defineProperty(huge, "size", { value: 11 * 1024 * 1024 });
    attachFile("slot-input-councilCert", huge);
    expect(screen.getByTestId("slot-error-councilCert")).toHaveTextContent(
      t.errors.uploadTooLarge,
    );
  });

  it("removes an attached document via its Remove button", () => {
    walkToStep(3, "doctor");
    attachDoctorFiles();
    fireEvent.click(screen.getByTestId("slot-remove-degrees"));
    expect(screen.queryByTestId("slot-file-degrees")).not.toBeInTheDocument();
    expect(screen.getByTestId("slot-input-degrees")).toBeInTheDocument();
  });

  it("lets a lab proceed while the optional accreditation slot stays empty", () => {
    walkToStep(3, "lab");
    expect(screen.getByTestId("slot-accreditations")).toHaveTextContent(
      t.optionalSuffix,
    );
    // Only the required partner slots block progression.
    attachFile(
      "slot-input-businessReg",
      new File(["gst"], "gst.pdf", { type: "application/pdf" }),
    );
    attachFile(
      "slot-input-kyc",
      new File(["kyc"], "kyc.pdf", { type: "application/pdf" }),
    );
    fireEvent.click(screen.getByTestId("pr-next"));
    expect(screen.getByTestId("pr-step-4")).toBeInTheDocument();
  });
});

describe("review & declarations with submission", () => {
  it("summarizes the entered data faithfully before declarations", () => {
    walkToStep(4, "doctor");
    const review = screen.getByTestId("pr-step-4");
    expect(review).toHaveTextContent("Dr. Asha Kumar");
    expect(review).toHaveTextContent("asha@example.com");
    expect(review).toHaveTextContent("9876543210");
    expect(review).toHaveTextContent(t.typeLabels.doctor);
    expect(review).toHaveTextContent("Jharkhand State Medical Council");
    expect(review).toHaveTextContent("council-cert.pdf");
    expect(screen.getByTestId("pr-review-creds-count")).toHaveTextContent(
      t.review.fileCount(3),
    );
  });

  it("blocks submit until all three declarations are ticked", () => {
    walkToStep(4, "doctor");
    fireEvent.click(screen.getByTestId("pr-submit"));
    expect(screen.getByTestId("decl-error-truth")).toHaveTextContent(
      t.errors.declarationRequired,
    );
    expect(screen.queryByTestId("pr-server-error")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("decl-truth"));
    fireEvent.click(screen.getByTestId("decl-consent"));
    fireEvent.click(screen.getByTestId("decl-terms"));
    fireEvent.click(screen.getByTestId("pr-submit"));

    expect(screen.getByTestId("pr-submit")).toBeDisabled();
  });

  it("shows server error with trace id on API failure", async () => {
    mockRegisterPartner.mockRejectedValueOnce(
      new (await import("@/lib/api-errors")).ApiError({
        code: "VALIDATION_ERROR",
        message: "Phone number already registered",
        trace_id: "abc123",
        details: {},
      }),
    );

    walkToStep(4, "doctor");
    fireEvent.click(screen.getByTestId("decl-truth"));
    fireEvent.click(screen.getByTestId("decl-consent"));
    fireEvent.click(screen.getByTestId("decl-terms"));
    fireEvent.click(screen.getByTestId("pr-submit"));

    const error = await screen.findByTestId("pr-server-error");
    expect(error).toHaveTextContent("Phone number already registered");
    expect(error).toHaveTextContent("Trace: abc123");
  });

  it("surfaces a session-mint refusal on the confirmation step without saving", async () => {
    const { AuthApiError: MockAuthApiError } = await import("@/lib/auth/api");
    mockIssuePartnerSession.mockRejectedValueOnce(
      new MockAuthApiError({
        code: "SESSION_REFUSED",
        message: "identity 1 is Unverified, not Active; verify the OTP first",
        trace_id: "trace-session-refused",
        details: {},
      }),
    );

    await submitToConfirm();
    await confirmWithCode();

    // The code verified but the mint was refused: the refusal surfaces as
    // calm partner-login copy on the confirmation step, nothing is saved,
    // and the wizard never routes onward.
    expect(await screen.findByTestId("pr-confirm-error")).toHaveTextContent(
      loginT.networkError,
    );
    expect(mockIssuePartnerSession).toHaveBeenCalledWith("+919876543210");
    expect(mockSaveSession).not.toHaveBeenCalled();
    expect(mockPostLoginTarget).not.toHaveBeenCalled();
  });

  it("registers, confirms the phone, then mints and saves the partner session", async () => {
    await submitToConfirm();

    // Registration alone never mints: the confirmation step issues the SMS
    // challenge and shows the code card with the verified number.
    expect(mockRegisterPartner).toHaveBeenCalledOnce();
    expect(mockRegisterPartner).toHaveBeenCalledWith(
      expect.objectContaining({
        phone: "+919876543210",
        partner_type: "doctor",
        practice_latitude: 23.99,
        practice_longitude: 83.99,
      }),
    );
    expect(mockPartnerLogin).toHaveBeenCalledWith("+919876543210");
    expect(mockIssuePartnerSession).not.toHaveBeenCalled();
    expect(screen.getByTestId("pr-confirm-phone")).toHaveTextContent(
      "+919876543210",
    );

    confirmWithCode();
    await vi.waitFor(
      () => {
        expect(mockIssuePartnerSession).toHaveBeenCalledOnce();
      },
      { timeout: 5000 },
    );

    expect(mockPartnerVerify).toHaveBeenCalledOnce();
    expect(mockPartnerVerify).toHaveBeenCalledWith("+919876543210", "123456");
    expect(mockSubmitCredentials).toHaveBeenCalledOnce();
    expect(mockSaveSession).toHaveBeenCalledOnce();
    expect(mockSaveSession).toHaveBeenCalledWith(
      expect.objectContaining({ jwt: "test-jwt" }),
      "+919876543210",
    );

    const verifyOrder = mockPartnerVerify.mock.invocationCallOrder[0];
    const sessionOrder = mockIssuePartnerSession.mock.invocationCallOrder[0];
    const saveOrder = mockSaveSession.mock.invocationCallOrder[0];
    const submitOrder = mockSubmitCredentials.mock.invocationCallOrder[0];
    expect(verifyOrder).toBeLessThan(sessionOrder);
    expect(sessionOrder).toBeLessThan(saveOrder);
    expect(saveOrder).toBeLessThan(submitOrder);
    expect(mockPostLoginTarget).toHaveBeenCalledWith({
      surface: "staff",
      roles: ["partner"],
      partnerState: "pending",
    });
  });

  it("passes through a 12-digit international-format phone unchanged", async () => {
    // 12-digit 91-prefixed form - the wizard must not double-prefix it.
    await submitToConfirm("919876543210");
    expect(mockPartnerLogin).toHaveBeenCalledWith("+919876543210");
    await confirmWithCode();
    await vi.waitFor(
      () => {
        expect(mockIssuePartnerSession).toHaveBeenCalledOnce();
      },
      { timeout: 5000 },
    );

    expect(mockRegisterPartner).toHaveBeenCalledWith(
      expect.objectContaining({ phone: "+919876543210" }),
    );
  });

  it("falls back to env-configured coordinates when geolocation is denied", async () => {
    // Override geolocation to deny BEFORE the wizard mounts so its mount-time
    // useEffect resolves to the env-configured fallback (Daltonganj).
    mockGeolocation((_success, error) => error({ code: 1, message: "denied" }));

    await submitToConfirm();
    await confirmWithCode();
    await vi.waitFor(
      () => {
        expect(mockIssuePartnerSession).toHaveBeenCalledOnce();
      },
      { timeout: 5000 },
    );

    expect(mockRegisterPartner).toHaveBeenCalledWith(
      expect.objectContaining({
        practice_latitude: 24.04,
        practice_longitude: 84.07,
      }),
    );
  });
});

describe("phone-confirmation step (F014-T08 #468)", () => {
  it("renders the confirmation card with phone, countdown and code input", async () => {
    await submitToConfirm();
    const step = screen.getByTestId("pr-step-5");
    expect(step).toHaveTextContent(t.phoneConfirm.title);
    expect(screen.getByTestId("pr-confirm-phone")).toHaveTextContent(
      "+919876543210",
    );
    expect(screen.getByTestId("pr-confirm-otp")).toBeInTheDocument();
    expect(screen.getByTestId("pr-confirm-countdown")).toHaveTextContent(
      /[0-9]/,
    );
    // No generic wizard footer on the confirmation step.
    expect(screen.queryByTestId("pr-submit")).not.toBeInTheDocument();
  });

  it("never mints when confirmation is skipped (back to review)", async () => {
    await submitToConfirm();
    fireEvent.click(screen.getByTestId("pr-confirm-back"));
    expect(screen.getByTestId("pr-step-4")).toBeInTheDocument();
    expect(mockIssuePartnerSession).not.toHaveBeenCalled();
    expect(mockSaveSession).not.toHaveBeenCalled();
    expect(mockPostLoginTarget).not.toHaveBeenCalled();
  });

  it("shows the demo OTP read-back banner on the confirmation step", async () => {
    vi.stubEnv("NEXT_PUBLIC_DEMO_MODE", "true");
    mockFetchDemoOtp.mockResolvedValueOnce("424242");

    await submitToConfirm();

    expect(
      await screen.findByTestId("pr-confirm-demo-banner"),
    ).toHaveTextContent(loginT.demoOtp("424242"));
  });

  it("renders the wrong-code refusal and never mints", async () => {
    mockPartnerVerify.mockResolvedValueOnce({
      outcome: "wrong_code",
      phone_e164: "+919876543210",
      identity_id: null,
      attempts_left: 4,
      lockout_remaining_seconds: null,
    });

    await submitToConfirm();
    await confirmWithCode("000000");

    expect(await screen.findByTestId("pr-confirm-error")).toHaveTextContent(
      loginT.wrongCode(4),
    );
    expect(mockIssuePartnerSession).not.toHaveBeenCalled();
    expect(mockSaveSession).not.toHaveBeenCalled();
    expect(screen.getByTestId("pr-step-5")).toBeInTheDocument();
  });

  it("renders the cooldown refusal copy on the confirmation step", async () => {
    mockPartnerLogin.mockResolvedValueOnce({
      outcome: "cooldown",
      phone_e164: "+919876543210",
      challenge_id: null,
      expires_in_seconds: null,
      cooldown_remaining_seconds: 45,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });

    await submitToConfirm();

    expect(
      await screen.findByTestId("pr-confirm-resend-cooldown"),
    ).toHaveTextContent(loginT.resendIn(45));
    expect(mockIssuePartnerSession).not.toHaveBeenCalled();
  });

  it("renders the lockout refusal copy on the confirmation step", async () => {
    mockPartnerLogin.mockResolvedValueOnce({
      outcome: "locked",
      phone_e164: "+919876543210",
      challenge_id: null,
      expires_in_seconds: null,
      cooldown_remaining_seconds: null,
      attempts_left: null,
      lockout_remaining_seconds: 900,
    });

    await submitToConfirm();

    expect(await screen.findByTestId("pr-confirm-lockout")).toHaveTextContent(
      loginT.lockout(15),
    );
    expect(mockIssuePartnerSession).not.toHaveBeenCalled();
  });

  it("renders the suspended refusal copy on the confirmation step", async () => {
    mockPartnerLogin.mockResolvedValueOnce({
      outcome: "suspended",
      phone_e164: "+919876543210",
      challenge_id: null,
      expires_in_seconds: null,
      cooldown_remaining_seconds: null,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });

    await submitToConfirm();

    expect(await screen.findByTestId("pr-confirm-error")).toHaveTextContent(
      loginT.suspendedNotice,
    );
    expect(mockIssuePartnerSession).not.toHaveBeenCalled();
  });

  it("re-verifies an existing partner's phone with a fresh code (duplicate resolution)", async () => {
    mockRegisterPartner.mockResolvedValueOnce({
      partner_id: 1,
      identity_id: 1,
      partner_type: "doctor",
      status: "Registered",
      round: 2,
      created: false,
    });

    await submitToConfirm();
    expect(mockPartnerLogin).toHaveBeenCalledWith("+919876543210");
    expect(mockRegisterPartner.mock.calls[0][0]).toMatchObject({
      phone: "+919876543210",
      partner_type: "doctor",
    });

    await confirmWithCode();
    await vi.waitFor(
      () => {
        expect(mockIssuePartnerSession).toHaveBeenCalledOnce();
      },
      { timeout: 5000 },
    );
    expect(mockPartnerVerify).toHaveBeenCalledWith("+919876543210", "123456");
  });

  it("re-issues the code when the confirm action finds no pending challenge", async () => {
    // First challenge issue lands in cooldown, so the flow never reaches the
    // otp stage; the confirm submit then re-issues and gets a real code.
    mockPartnerLogin.mockResolvedValueOnce({
      outcome: "cooldown",
      phone_e164: "+919876543210",
      challenge_id: null,
      expires_in_seconds: null,
      cooldown_remaining_seconds: 45,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });

    await submitToConfirm();
    await screen.findByTestId("pr-confirm-resend-cooldown");
    expect(mockPartnerLogin).toHaveBeenCalledTimes(1);
    expect(mockIssuePartnerSession).not.toHaveBeenCalled();

    mockPartnerLogin.mockResolvedValueOnce(CONFIRM_LOGIN_OK);
    await act(async () => {
      fireEvent.click(screen.getByTestId("pr-confirm-submit"));
    });

    expect(await screen.findByTestId("pr-confirm-attempts")).toHaveTextContent(
      loginT.attemptsLeft(5),
    );
    expect(mockPartnerLogin).toHaveBeenCalledTimes(2);
    expect(mockPartnerLogin).toHaveBeenLastCalledWith("+919876543210");
  });

  it("renders the suspended refusal copy in Hindi when the locale is hi", async () => {
    const hiLoginT = STRINGS.hi.staffAuth.login;
    mockPartnerLogin.mockResolvedValueOnce({
      outcome: "suspended",
      phone_e164: "+919876543210",
      challenge_id: null,
      expires_in_seconds: null,
      cooldown_remaining_seconds: null,
      attempts_left: null,
      lockout_remaining_seconds: null,
    });

    // The refusal string is captured into state by the OTP reducer when the
    // phone challenge resolves, so the locale must already be Hindi before
    // the walk reaches the confirmation step.
    const flipToHindi = () => {
      render(
        <>
          <ProviderRegisterWizard presetType="doctor" />
          <LangFlip />
        </>,
      );
      act(() => {
        fireEvent.click(screen.getByTestId("lang-flip"));
      });
    };

    await submitToConfirm(undefined, flipToHindi);

    // The refusal copy renders in Hindi, not the English fallback.
    expect(await screen.findByTestId("pr-confirm-error")).toHaveTextContent(
      hiLoginT.suspendedNotice,
    );
    expect(screen.queryByText(loginT.suspendedNotice)).not.toBeInTheDocument();
  });
});
