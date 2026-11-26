// PHASE-5 T6 (#285): Operator verification detail + decision tests -
// rendering partner profile, credentials, verification history, audit events,
// approve/reject flows, error states, and navigation after decision.

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import VerificationDetailPage from "./page";
import {
  fetchVerificationDetail,
  submitOperatorDecision,
  type PartnerVerificationDetail,
  type CredentialDetail,
  type VerificationRound,
  type AuditEventDetail,
} from "@/lib/operator/api";
import type { PartnerView } from "@/lib/partner/api";

const mockPush = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ partner_id: "42" }),
  useRouter: () => ({ push: mockPush }),
}));

vi.mock("@/lib/operator/api", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/operator/api")>();
  return {
    ...mod,
    fetchVerificationDetail: vi.fn(),
    submitOperatorDecision: vi.fn(),
  };
});

vi.mock("@/lib/auth/AuthContext", () => ({
  useAuth: () => ({
    user: { id: 1, phone: "+911234567890", roles: ["operator"] },
    selectedRole: "operator",
    switchRole: vi.fn(),
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
}));

const mockFetchDetail = vi.mocked(fetchVerificationDetail);
const mockSubmitDecision = vi.mocked(submitOperatorDecision);

function makeCredential(
  overrides: Partial<CredentialDetail> = {},
): CredentialDetail {
  return {
    credential_id: 1,
    credential_type: "Business registration (GST)",
    verified: true,
    expires_at: null,
    artifact_refs: { pdf: "https://cdn.example.com/gst.pdf" },
    ...overrides,
  };
}

function makeRound(
  overrides: Partial<VerificationRound> = {},
): VerificationRound {
  return {
    round: 1,
    status: "Under Verification",
    decision: null,
    decision_reason: null,
    decision_by: null,
    decided_at: null,
    created_at: "2026-08-19T14:15:00Z",
    ...overrides,
  };
}

function makeAuditEvent(
  overrides: Partial<AuditEventDetail> = {},
): AuditEventDetail {
  return {
    id: "evt-001",
    event_type: "partner.submitted",
    actor_id: "usr-10",
    target_id: "partner-42",
    scope: "verification",
    metadata: {},
    timestamp: "2026-08-19T14:15:00Z",
    prev_hash: "abc123",
    hash: "def456abc789",
    ...overrides,
  };
}

function makeDetail(
  overrides: Partial<PartnerVerificationDetail> = {},
): PartnerVerificationDetail {
  return {
    partner_id: 42,
    identity_id: 100,
    partner_type: "lab",
    status: "Under Verification",
    practice_name: "Pioneer Diagnostics",
    practice_address: "Court Rd, Daltonganj",
    service_area_id: 5,
    created_at: "2026-08-19T14:15:00Z",
    credentials: [makeCredential()],
    verification_history: [makeRound()],
    audit_events: [makeAuditEvent()],
    audit_link: null,
    ...overrides,
  };
}

function resolveWith(data: PartnerVerificationDetail | null) {
  mockFetchDetail.mockImplementation(() =>
    data === null
      ? Promise.reject(new Error("network down"))
      : (Promise.resolve(data) as Promise<PartnerVerificationDetail>),
  );
}

beforeEach(() => {
  resolveWith(makeDetail());
  mockSubmitDecision.mockImplementation(() =>
    Promise.resolve({
      partner_id: 42,
      status: "Active",
      round: 1,
    } as PartnerView),
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("VerificationDetailPage", () => {
  it("shows a loading skeleton while fetching", () => {
    mockFetchDetail.mockImplementation(
      () => new Promise<PartnerVerificationDetail>(() => {}),
    );
    render(<VerificationDetailPage />);
    expect(screen.getByTestId("detail-skeleton")).toBeTruthy();
  });

  it("renders partner profile on load", async () => {
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("partner-profile")).toBeTruthy();
    });
    const profile = screen.getByTestId("partner-profile");
    expect(within(profile).getByText("Pioneer Diagnostics")).toBeTruthy();
    expect(within(profile).getByText("Court Rd, Daltonganj")).toBeTruthy();
    expect(within(profile).getByText("Lab")).toBeTruthy();
  });

  it("renders credentials section", async () => {
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("credentials-card")).toBeTruthy();
    });
    expect(screen.getByText("Business registration (GST)")).toBeTruthy();
  });

  it("shows verified badge for verified credentials", async () => {
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByText("Verified")).toBeTruthy();
    });
  });

  it("shows pending badge for unverified credentials", async () => {
    resolveWith(
      makeDetail({
        credentials: [makeCredential({ verified: false })],
      }),
    );
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByText("Pending")).toBeTruthy();
    });
  });

  it("renders verification history table", async () => {
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("verification-history")).toBeTruthy();
    });
  });

  it("renders audit timeline", async () => {
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("audit-timeline")).toBeTruthy();
    });
    expect(screen.getByText("partner.submitted")).toBeTruthy();
  });

  it("shows error banner on fetch failure", async () => {
    resolveWith(null);
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("error-banner")).toBeTruthy();
    });
    expect(
      screen.getByText("Could not load the verification detail."),
    ).toBeTruthy();
  });

  it("retry reloads the detail", async () => {
    resolveWith(null);
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("error-banner")).toBeTruthy();
    });
    resolveWith(makeDetail());
    fireEvent.click(screen.getByTestId("error-banner-retry"));
    await waitFor(() => {
      expect(screen.getByTestId("partner-profile")).toBeTruthy();
    });
  });

  it("renders approve and reject buttons", async () => {
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("btn-approve")).toBeTruthy();
    });
    expect(screen.getByTestId("btn-reject")).toBeTruthy();
  });

  it("opens approve confirmation sheet", async () => {
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("btn-approve")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("btn-approve"));
    await waitFor(() => {
      expect(screen.getByTestId("confirm-approve")).toBeTruthy();
    });
  });

  it("submits approve decision and navigates back", async () => {
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("btn-approve")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("btn-approve"));
    await waitFor(() => {
      expect(screen.getByTestId("confirm-approve")).toBeTruthy();
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("confirm-approve"));
    });
    await waitFor(() => {
      expect(mockSubmitDecision).toHaveBeenCalledWith(42, { approve: true });
      expect(mockPush).toHaveBeenCalledWith("/operator");
    });
  });

  it("opens reject sheet and requires reason", async () => {
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("btn-reject")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("btn-reject"));
    await waitFor(() => {
      expect(screen.getByTestId("reject-reason-input")).toBeTruthy();
    });
    expect(screen.getByTestId("confirm-reject")).toBeDisabled();
  });

  it("enables reject submit when reason is non-empty", async () => {
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("btn-reject")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("btn-reject"));
    await waitFor(() => {
      expect(screen.getByTestId("reject-reason-input")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("reject-reason-input"), {
      target: { value: "Document is blurry" },
    });
    expect(screen.getByTestId("confirm-reject")).not.toBeDisabled();
  });

  it("submits reject decision with reason and navigates back", async () => {
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("btn-reject")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("btn-reject"));
    await waitFor(() => {
      expect(screen.getByTestId("reject-reason-input")).toBeTruthy();
    });
    fireEvent.change(screen.getByTestId("reject-reason-input"), {
      target: { value: "Document is blurry" },
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("confirm-reject"));
    });
    await waitFor(() => {
      expect(mockSubmitDecision).toHaveBeenCalledWith(42, {
        approve: false,
        reason: "Document is blurry",
      });
      expect(mockPush).toHaveBeenCalledWith("/operator");
    });
  });

  it("shows error banner when decision submission fails", async () => {
    mockSubmitDecision.mockImplementation(() =>
      Promise.reject(new Error("Server error")),
    );
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("btn-approve")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("btn-approve"));
    await waitFor(() => {
      expect(screen.getByTestId("confirm-approve")).toBeTruthy();
    });
    await act(async () => {
      fireEvent.click(screen.getByTestId("confirm-approve"));
    });
    await waitFor(() => {
      expect(screen.getByText("Server error")).toBeTruthy();
    });
  });

  it("shows empty state when no credentials", async () => {
    resolveWith(makeDetail({ credentials: [] }));
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByText("No credentials uploaded.")).toBeTruthy();
    });
  });

  it("hides history and audit sections when empty", async () => {
    resolveWith(
      makeDetail({
        verification_history: [],
        audit_events: [],
      }),
    );
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("partner-profile")).toBeTruthy();
    });
    expect(screen.queryByTestId("verification-history")).toBeNull();
    expect(screen.queryByTestId("audit-timeline")).toBeNull();
  });

  it("shows partner type badge with correct style", async () => {
    resolveWith(makeDetail({ partner_type: "doctor" }));
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByText("Doctor")).toBeTruthy();
    });
  });

  it("passes partner_id from URL params", async () => {
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(mockFetchDetail).toHaveBeenCalledWith(42);
    });
  });

  it("renders breadcrumbs", async () => {
    render(<VerificationDetailPage />);
    await waitFor(() => {
      expect(screen.getByTestId("breadcrumbs")).toBeTruthy();
    });
    expect(screen.getByText("Verifications")).toBeTruthy();
  });
});
