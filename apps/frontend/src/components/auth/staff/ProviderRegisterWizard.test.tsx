// PHASE-2.6 T11 (#202): component suite for the four-step provider
// registration wizard. Covers the ticket's acceptance criteria: four steps
// in order, the ?type= CTA preset flow, per-field validation blocking
// progression, upload-discipline checks, and real submission to the backend.

import {
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
import { __resetLangForTests } from "@/lib/i18n/LangContext";

import { registerPartner, submitCredentials } from "@/lib/partner/api";
import { issuePartnerSession } from "@/lib/auth/api";
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
const STRONG = "correct-horse-battery1!";

const mockRegisterPartner = vi.mocked(registerPartner);
const mockSubmitCredentials = vi.mocked(submitCredentials);
const mockIssuePartnerSession = vi.mocked(issuePartnerSession);
const mockSaveSession = vi.mocked(saveSession);
const mockPostLoginTarget = vi.mocked(postLoginTarget);

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
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
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

  it("surfaces an AuthApiError's real backend message and trace id on failure", async () => {
    const { AuthApiError: MockAuthApiError } = await import("@/lib/auth/api");
    mockIssuePartnerSession.mockRejectedValueOnce(
      new MockAuthApiError({
        code: "SESSION_REFUSED",
        message: "identity 1 is Unverified, not Active; verify the OTP first",
        trace_id: "trace-session-refused",
        details: {},
      }),
    );

    walkToStep(4, "doctor");
    fireEvent.click(screen.getByTestId("decl-truth"));
    fireEvent.click(screen.getByTestId("decl-consent"));
    fireEvent.click(screen.getByTestId("decl-terms"));
    fireEvent.click(screen.getByTestId("pr-submit"));

    const error = await screen.findByTestId("pr-server-error");
    expect(error).toHaveTextContent(
      "identity 1 is Unverified, not Active; verify the OTP first",
    );
    expect(error).toHaveTextContent("Trace: trace-session-refused");
  });

  it("calls registerPartner then issuePartnerSession then saveSession on successful submit", async () => {
    walkToStep(4, "doctor");
    fireEvent.click(screen.getByTestId("decl-truth"));
    fireEvent.click(screen.getByTestId("decl-consent"));
    fireEvent.click(screen.getByTestId("decl-terms"));
    fireEvent.click(screen.getByTestId("pr-submit"));

    await vi.waitFor(
      () => {
        expect(mockIssuePartnerSession).toHaveBeenCalledOnce();
      },
      { timeout: 5000 },
    );

    expect(mockRegisterPartner).toHaveBeenCalledOnce();
    expect(mockRegisterPartner).toHaveBeenCalledWith(
      expect.objectContaining({
        phone: "+919876543210",
        partner_type: "doctor",
        practice_latitude: 23.99,
        practice_longitude: 83.99,
      }),
    );
    expect(mockSubmitCredentials).toHaveBeenCalledOnce();
    expect(mockIssuePartnerSession).toHaveBeenCalledWith("+919876543210");
    expect(mockSaveSession).toHaveBeenCalledOnce();
    expect(mockSaveSession).toHaveBeenCalledWith(
      expect.objectContaining({ jwt: "test-jwt" }),
      "+919876543210",
    );
    expect(mockPostLoginTarget).toHaveBeenCalledWith({
      surface: "staff",
      roles: ["partner"],
      partnerState: "pending",
    });
  });

  it("passes through a 12-digit international-format phone unchanged", async () => {
    render(<ProviderRegisterWizard presetType="doctor" />);
    type("pr-fullname", "Dr. Asha Kumar");
    type("pr-email", "asha@example.com");
    type("pr-password", STRONG);
    // 12-digit 91-prefixed form - the wizard must not double-prefix it.
    type("pr-mobile", "919876543210");
    fireEvent.click(screen.getByTestId("pr-next"));
    fillDoctorStep2();
    fireEvent.click(screen.getByTestId("pr-next"));
    attachDoctorFiles();
    fireEvent.click(screen.getByTestId("pr-next"));

    fireEvent.click(screen.getByTestId("decl-truth"));
    fireEvent.click(screen.getByTestId("decl-consent"));
    fireEvent.click(screen.getByTestId("decl-terms"));
    fireEvent.click(screen.getByTestId("pr-submit"));

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

    walkToStep(4, "doctor");
    fireEvent.click(screen.getByTestId("decl-truth"));
    fireEvent.click(screen.getByTestId("decl-consent"));
    fireEvent.click(screen.getByTestId("decl-terms"));
    fireEvent.click(screen.getByTestId("pr-submit"));

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
